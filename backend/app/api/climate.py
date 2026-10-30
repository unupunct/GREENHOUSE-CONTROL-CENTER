from __future__ import annotations

import json
import time
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from sqlalchemy import select

from app.automation import climate_rules as cr
from app.automation.climate import ClimateSettings, save_settings
from app.core.models import Actuator, ClimateRule, DailyStat, LightProgram, Sensor, Window
from app.services import events

router = APIRouter(prefix="/api/climate")
ID = r"^[a-z0-9_]{2,48}$"
HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


def _db(r: Request):
    return r.app.state.db


def _eng(r: Request):
    return r.app.state.climate


def _reload(r: Request) -> None:
    r.app.state.climate.reload()


def _need_sensors(db, ids: list[str | None], what: str) -> None:
    with db.session() as s:
        for sid in ids:
            if sid and s.get(Sensor, sid) is None:
                raise HTTPException(422, f"{what}: unknown sensor '{sid}'")


def _output(db, oid: str, what: str, kinds_not: tuple[str, ...] = ()) -> Actuator:
    from app.hal.outputs import CLIMATE_KINDS
    with db.session() as s:
        a = s.get(Actuator, oid)
    if a is None or a.kind not in CLIMATE_KINDS:
        raise HTTPException(422, f"{what}: '{oid}' is not a climate output")
    if a.kind in kinds_not:
        raise HTTPException(422, f"{what}: '{oid}' is a {a.kind} output")
    return a


# ----------------------------------------------------------------- views

def _rule(r: ClimateRule) -> dict:
    d = {c.name: getattr(r, c.name) for c in ClimateRule.__table__.columns}
    d["conditions"], d["actions"] = json.loads(r.conditions), json.loads(r.actions)
    return d


@router.get("/setup")
def setup(request: Request):
    from app.api.irrigation import _act
    from app.hal.outputs import CLIMATE_KINDS
    with _db(request).session() as s:
        return {
            "outputs": [_act(a) for a in s.scalars(select(Actuator).where(Actuator.kind.in_(CLIMATE_KINDS)).order_by(Actuator.id))],
            "rules": [_rule(r) for r in s.scalars(select(ClimateRule).order_by(ClimateRule.priority.desc(), ClimateRule.id))],
            "windows": [{c.name: getattr(w, c.name) for c in Window.__table__.columns} for w in s.scalars(select(Window).order_by(Window.id))],
            "lights": [{**{c.name: getattr(lp, c.name) for c in LightProgram.__table__.columns},
                        "output_ids": json.loads(lp.output_ids)} for lp in s.scalars(select(LightProgram).order_by(LightProgram.id))],
            "settings": _eng(request).cfg.g.model_dump(),
            "output_drivers": request.app.state.outputs.describe(),
            "kinds": list(CLIMATE_KINDS),
        }


@router.get("/status")
def status(request: Request):
    return _eng(request).status()


@router.put("/settings")
def put_settings(g: ClimateSettings, request: Request):
    save_settings(_db(request), g)
    _reload(request)
    events.log_event(_db(request), "info", "climate",
                     f"Climate settings changed (automatic climate control {'ON' if g.auto_enabled else 'OFF'})")
    return g.model_dump()


# ----------------------------------------------------------------- rules

class SensorCond(BaseModel):
    type: Literal["sensor"]
    sensors: list[str] = Field(min_length=1)
    agg: Literal["mean", "min", "max"] = "mean"
    op: Literal[">", "<"]
    on: float
    off: float | None = None


class VpdCond(BaseModel):
    type: Literal["vpd"]
    temp_sensors: list[str] = Field(min_length=1)
    rh_sensors: list[str] = Field(min_length=1)
    op: Literal[">", "<"]
    on: float
    off: float | None = None


class TimeCond(BaseModel):
    type: Literal["time"]
    start: str = Field(pattern=HHMM)
    end: str = Field(pattern=HHMM)


class MonthCond(BaseModel):
    type: Literal["month"]
    months: list[int] = Field(min_length=1)

    @field_validator("months")
    @classmethod
    def _m(cls, v):
        if any(m < 1 or m > 12 for m in v):
            raise ValueError("months are 1-12")
        return sorted(set(v))


class OutputCond(BaseModel):
    type: Literal["output"]
    output_id: str
    state: Literal["on", "off"] = "on"


Condition = Annotated[SensorCond | VpdCond | TimeCond | MonthCond | OutputCond, Field(discriminator="type")]


class OutputAction(BaseModel):
    output_id: str
    state: Literal["on", "off"] = "on"


class WindowAction(BaseModel):
    window_id: str
    position_pct: float = Field(ge=0, le=100)


class RuleIn(BaseModel):
    id: str = Field(pattern=ID)
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    priority: int = Field(50, ge=0, le=99)
    match: Literal["all", "any"] = "all"
    conditions: list[Condition] = Field(min_length=1)
    actions: list[OutputAction | WindowAction] = Field(min_length=1)
    on_delay_s: int = Field(0, ge=0, le=86400)
    off_delay_s: int = Field(0, ge=0, le=86400)
    min_on_s: int = Field(0, ge=0, le=86400)
    min_off_s: int = Field(0, ge=0, le=86400)
    max_on_s: int | None = Field(None, gt=0, le=604800)
    cooldown_s: int = Field(0, ge=0, le=86400)
    notify: bool = False
    on_fault: Literal["off", "hold"] = "off"

    @model_validator(mode="after")
    def _hyst(self):
        for c in self.conditions:
            if isinstance(c, (SensorCond, VpdCond)):
                off = c.on if c.off is None else c.off
                if not cr.hysteresis_valid(c.op, c.on, off):
                    raise ValueError(f"release value must be {'<=' if c.op == '>' else '>='} the trigger value (hysteresis)")
        return self


def _validate_rule(body: RuleIn, request: Request) -> tuple[list[dict], list[dict]]:
    db = _db(request)
    conds = []
    for c in body.conditions:
        d = c.model_dump()
        if isinstance(c, SensorCond):
            _need_sensors(db, c.sensors, "condition")
        if isinstance(c, VpdCond):
            _need_sensors(db, c.temp_sensors + c.rh_sensors, "condition")
        if isinstance(c, OutputCond):
            _output(db, c.output_id, "condition")
        if isinstance(c, (SensorCond, VpdCond)) and d.get("off") is None:
            d["off"] = d["on"]
        conds.append(d)
    with db.session() as s:
        in_lights = {o for lp in s.scalars(select(LightProgram)) for o in json.loads(lp.output_ids)}
        wins = {w.id for w in s.scalars(select(Window))}
    acts = []
    for a in body.actions:
        if isinstance(a, WindowAction):
            if a.window_id not in wins:
                raise HTTPException(422, f"action: unknown window '{a.window_id}'")
        else:
            _output(db, a.output_id, "action", kinds_not=("motor",))
            if a.output_id in in_lights:
                raise HTTPException(422, f"action: '{a.output_id}' belongs to a lighting program")
        acts.append(a.model_dump())
    return conds, acts


def _write_rule(r: ClimateRule, b: RuleIn, conds, acts, generated: bool = False) -> None:
    for k in ("name", "enabled", "priority", "match", "on_delay_s", "off_delay_s", "min_on_s", "min_off_s",
              "max_on_s", "cooldown_s", "notify", "on_fault"):
        setattr(r, k, getattr(b, k))
    r.conditions, r.actions, r.generated = json.dumps(conds), json.dumps(acts), generated


@router.post("/rules", status_code=201)
def create_rule(body: RuleIn, request: Request):
    conds, acts = _validate_rule(body, request)
    with _db(request).session() as s:
        if s.get(ClimateRule, body.id):
            raise HTTPException(409, "id already exists")
        r = ClimateRule(id=body.id)
        _write_rule(r, body, conds, acts)
        s.add(r)
    _reload(request)
    return {"id": body.id}


@router.put("/rules/{rule_id}")
def update_rule(rule_id: str, body: RuleIn, request: Request):
    if body.id != rule_id:
        raise HTTPException(422, "id cannot be changed")
    conds, acts = _validate_rule(body, request)
    with _db(request).session() as s:
        r = s.get(ClimateRule, rule_id)
        if r is None:
            raise HTTPException(404, "not found")
        _write_rule(r, body, conds, acts, r.generated)
    _reload(request)
    return {"ok": True}


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: str, request: Request):
    with _db(request).session() as s:
        r = s.get(ClimateRule, rule_id)
        if r is None:
            raise HTTPException(404, "not found")
        s.delete(r)
    _reload(request)
    return {"ok": True}


# --------------------------------------------------------------- windows

class WindowIn(BaseModel):
    id: str = Field(pattern=ID)
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["vent", "shade"] = "vent"
    open_output_id: str
    close_output_id: str
    travel_time_s: float = Field(gt=0, le=3600)
    open_limit_sensor_id: str | None = None
    closed_limit_sensor_id: str | None = None
    rain_sensor_id: str | None = None
    wind_sensor_id: str | None = None
    wind_max_ms: float | None = Field(None, gt=0)
    min_step_pct: float = Field(5.0, ge=0.5, le=50)
    min_rest_s: float = Field(30.0, ge=0, le=3600)
    enabled: bool = True


def _validate_window(b: WindowIn, request: Request) -> None:
    db = _db(request)
    if b.open_output_id == b.close_output_id:
        raise HTTPException(422, "open and close must be different outputs")
    outs = [_output(db, b.open_output_id, "open output"), _output(db, b.close_output_id, "close output")]
    for a in outs:
        if a.kind != "motor":
            raise HTTPException(422, f"'{a.id}' must be an output of kind 'motor'")
        if a.max_runtime_s < b.travel_time_s * 1.2:
            raise HTTPException(422, f"'{a.id}' maximum runtime ({a.max_runtime_s}s) must be at least 1.2 x the travel time "
                                     f"({b.travel_time_s * 1.2:.0f}s)")
    if b.wind_max_ms is not None and not b.wind_sensor_id:
        raise HTTPException(422, "wind limit needs a wind sensor")
    _need_sensors(db, [b.open_limit_sensor_id, b.closed_limit_sensor_id, b.rain_sensor_id, b.wind_sensor_id], "window")
    with db.session() as s:
        for w in s.scalars(select(Window)):
            if w.id != b.id and ({w.open_output_id, w.close_output_id} & {b.open_output_id, b.close_output_id}):
                raise HTTPException(409, f"an output is already used by window '{w.id}'")


@router.post("/windows", status_code=201)
def create_window(body: WindowIn, request: Request):
    _validate_window(body, request)
    with _db(request).session() as s:
        if s.get(Window, body.id):
            raise HTTPException(409, "id already exists")
        s.add(Window(**body.model_dump()))
    _reload(request)
    return {"id": body.id}


@router.put("/windows/{wid}")
def update_window(wid: str, body: WindowIn, request: Request):
    if body.id != wid:
        raise HTTPException(422, "id cannot be changed")
    if _eng(request).win.get(wid) and _eng(request).win[wid].moving:
        raise HTTPException(409, "wait until the window stops moving")
    _validate_window(body, request)
    with _db(request).session() as s:
        w = s.get(Window, wid)
        if w is None:
            raise HTTPException(404, "not found")
        for k, v in body.model_dump().items():
            setattr(w, k, v)
    _reload(request)
    return {"ok": True}


@router.delete("/windows/{wid}")
def delete_window(wid: str, request: Request):
    with _db(request).session() as s:
        w = s.get(Window, wid)
        if w is None:
            raise HTTPException(404, "not found")
        if wid in {a["window_id"] for r in s.scalars(select(ClimateRule)) for a in json.loads(r.actions) if "window_id" in a}:
            raise HTTPException(409, "a rule uses this window")
        s.delete(w)
    _reload(request)
    return {"ok": True}


class PositionIn(BaseModel):
    position_pct: float = Field(ge=0, le=100)
    duration_s: float = Field(1800, gt=0, le=86400)


@router.post("/windows/{wid}/position")
def window_position(wid: str, body: PositionIn, request: Request):
    ok, msg = _eng(request).hold_window(wid, body.position_pct, body.duration_s, _eng(request).now())
    if not ok:
        raise HTTPException(409, msg)
    return {"ok": True, "detail": msg}


@router.post("/windows/{wid}/release")
def window_release(wid: str, request: Request):
    _eng(request).release_window(wid)
    return {"ok": True}


@router.post("/outputs/{oid}/release")
def output_release(oid: str, request: Request):
    _eng(request).release_output(oid)
    return {"ok": True}


# -------------------------------------------------------------- lighting

class LightIn(BaseModel):
    id: str = Field(pattern=ID)
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    output_ids: list[str] = Field(min_length=1)
    mode: Literal["photoperiod", "dli"] = "photoperiod"
    start_time: str = Field("06:00", pattern=HHMM)
    photoperiod_h: float = Field(16.0, gt=0, le=24)
    ppfd_sensor_id: str | None = None
    dli_target: float | None = Field(None, gt=0)
    on_below_ppfd: float | None = Field(None, ge=0)
    off_above_ppfd: float | None = Field(None, ge=0)
    power_sensor_id: str | None = None


@router.post("/lights", status_code=201)
def create_light(body: LightIn, request: Request):
    return _upsert_light(body, request, True)


@router.put("/lights/{lid}")
def update_light(lid: str, body: LightIn, request: Request):
    if body.id != lid:
        raise HTTPException(422, "id cannot be changed")
    return _upsert_light(body, request, False)


def _upsert_light(b: LightIn, request: Request, create: bool):
    db = _db(request)
    for oid in b.output_ids:
        _output(db, oid, "lighting output")
        with db.session() as s:
            if s.get(Actuator, oid).kind != "light":
                raise HTTPException(422, f"'{oid}' must be an output of kind 'light'")
            for lp in s.scalars(select(LightProgram)):
                if lp.id != b.id and oid in json.loads(lp.output_ids):
                    raise HTTPException(409, f"'{oid}' already belongs to program '{lp.id}'")
            for r in s.scalars(select(ClimateRule)):
                if f'"{oid}"' in r.actions:
                    raise HTTPException(409, f"'{oid}' is used by rule '{r.id}'")
    if b.mode == "dli":
        if not b.ppfd_sensor_id or b.dli_target is None or b.on_below_ppfd is None or b.off_above_ppfd is None:
            raise HTTPException(422, "DLI mode needs a PPFD sensor, target DLI, and on-below/off-above PPFD values")
        if b.off_above_ppfd < b.on_below_ppfd:
            raise HTTPException(422, "off-above PPFD must be at least the on-below PPFD")
    _need_sensors(db, [b.ppfd_sensor_id, b.power_sensor_id], "lighting")
    with db.session() as s:
        for oid in b.output_ids:
            a = s.get(Actuator, oid)
            if a.max_runtime_s < b.photoperiod_h * 3600:
                raise HTTPException(422, f"'{oid}' maximum runtime ({a.max_runtime_s}s) is shorter than the photoperiod "
                                         f"({b.photoperiod_h * 3600:.0f}s): raise it or the lights would be cut off")
    with db.session() as s:
        lp = s.get(LightProgram, b.id)
        if create and lp:
            raise HTTPException(409, "id already exists")
        if not create and lp is None:
            raise HTTPException(404, "not found")
        lp = lp or LightProgram(id=b.id)
        for k, v in b.model_dump().items():
            setattr(lp, k, json.dumps(v) if k == "output_ids" else v)
        s.merge(lp)
    _reload(request)
    return {"id": b.id}


@router.delete("/lights/{lid}")
def delete_light(lid: str, request: Request):
    with _db(request).session() as s:
        lp = s.get(LightProgram, lid)
        if lp is None:
            raise HTTPException(404, "not found")
        s.delete(lp)
    _reload(request)
    return {"ok": True}


@router.get("/lighting/history")
def lighting_history(request: Request, days: int = 30):
    since = time.strftime("%Y-%m-%d", time.localtime(time.time() - max(1, min(days, 366)) * 86400))
    with _db(request).session() as s:
        rows = s.scalars(select(DailyStat).where(DailyStat.date >= since).order_by(DailyStat.date)).all()
    out: dict[str, dict] = {}
    for r in rows:
        out.setdefault(r.date, {"date": r.date})[r.key] = r.value
    cur = _eng(request).status()["lighting"]
    if cur["date"]:
        out.setdefault(cur["date"], {"date": cur["date"]}).update(dli_mol=cur["dli_mol"], light_kwh=cur["light_kwh"])
    return {"days": [out[k] for k in sorted(out)], "note": "dli_mol = PAR-sensor reading integrated over the local day"}


# ------------------------------------------------------- setpoint template

class SetpointTemplate(BaseModel):
    """Generate temperature rules from setpoints YOU supply (nothing is assumed)."""

    temp_sensors: list[str] = Field(min_length=1)
    day_start: str = Field(pattern=HHMM)
    night_start: str = Field(pattern=HHMM)
    heater_id: str | None = None
    circulation_fan_id: str | None = None
    day_heat_on_below: float | None = None
    day_heat_off_above: float | None = None
    night_heat_on_below: float | None = None
    night_heat_off_above: float | None = None
    vent_window_ids: list[str] = []
    vent_open_above: float | None = None
    vent_close_below: float | None = None
    vent_open_pct: float = Field(100, ge=0, le=100)
    exhaust_fan_ids: list[str] = []
    fan_on_above: float | None = None
    fan_off_below: float | None = None
    notify_on_fan: bool = False


@router.post("/templates/setpoints")
def apply_template(t: SetpointTemplate, request: Request):
    """Replaces all previously generated rules (ids starting 'tpl_') with a fresh set."""
    db = _db(request)
    _need_sensors(db, t.temp_sensors, "template")
    rules: list[RuleIn] = []
    try:
        return _build_template(t, request, db, rules)
    except ValidationError as exc:
        raise HTTPException(422, "; ".join(e["msg"] for e in exc.errors())) from exc


def _build_template(t: SetpointTemplate, request: Request, db, rules: list[RuleIn]):
    cond = lambda op, on, off: {"type": "sensor", "sensors": t.temp_sensors, "agg": "mean", "op": op, "on": on, "off": off}  # noqa: E731

    def heat(name, start, end, on, off):
        if on is None or off is None:
            return
        actions = [{"output_id": t.heater_id, "state": "on"}]
        if t.circulation_fan_id:
            actions.append({"output_id": t.circulation_fan_id, "state": "on"})
        rules.append(RuleIn.model_validate({
            "id": f"tpl_heat_{name}", "name": f"Heating ({name})", "priority": 50, "on_delay_s": 30, "min_on_s": 60,
            "conditions": [{"type": "time", "start": start, "end": end}, cond("<", on, off)], "actions": actions}))

    if t.heater_id:
        heat("day", t.day_start, t.night_start, t.day_heat_on_below, t.day_heat_off_above)
        heat("night", t.night_start, t.day_start, t.night_heat_on_below, t.night_heat_off_above)
    if t.vent_window_ids and t.vent_open_above is not None and t.vent_close_below is not None:
        rules.append(RuleIn.model_validate({
            "id": "tpl_vent", "name": "Ventilation windows", "priority": 50, "min_on_s": 60,
            "conditions": [cond(">", t.vent_open_above, t.vent_close_below)],
            "actions": [{"window_id": w, "position_pct": t.vent_open_pct} for w in t.vent_window_ids]}))
    if t.exhaust_fan_ids and t.fan_on_above is not None and t.fan_off_below is not None:
        acts = [{"output_id": f, "state": "on"} for f in t.exhaust_fan_ids]
        acts += [{"window_id": w, "position_pct": 100} for w in t.vent_window_ids]
        rules.append(RuleIn.model_validate({
            "id": "tpl_fans", "name": "Exhaust fans", "priority": 55, "min_on_s": 60, "notify": t.notify_on_fan,
            "conditions": [cond(">", t.fan_on_above, t.fan_off_below)], "actions": acts}))
    if not rules:
        raise HTTPException(422, "nothing to generate: supply the setpoints and the equipment they control")
    prepared = [(r, *_validate_rule(r, request)) for r in rules]
    with db.session() as s:
        for old in s.scalars(select(ClimateRule).where(ClimateRule.generated.is_(True))):
            s.delete(old)
        s.flush()
        for r, conds, acts in prepared:
            row = ClimateRule(id=r.id)
            _write_rule(row, r, conds, acts, generated=True)
            s.add(row)
    _reload(request)
    events.log_event(db, "info", "climate", f"Generated {len(rules)} rule(s) from setpoints")
    return {"rules": [r.id for r in rules]}
