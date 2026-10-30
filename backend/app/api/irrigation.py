from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select

from app.automation.engine import IrrigationSettings, save_settings
from app.core.models import Actuator, Alert, IrrigationRun, Sensor, Tank, Zone
from app.hal.outputs import IRRIGATION_KINDS, OutputKind
from app.services import commissioning, events

router = APIRouter(prefix="/api")
ID = r"^[a-z0-9_]{2,48}$"


def _db(r: Request):
    return r.app.state.db


def _eng(r: Request):
    return r.app.state.engine


def _sensor_exists(db, sid: str | None, what: str) -> None:
    if sid:
        with db.session() as s:
            if s.get(Sensor, sid) is None:
                raise HTTPException(422, f"{what}: unknown sensor '{sid}'")


# -------------------------------------------------------------- setup view

def _act(a: Actuator) -> dict:
    return {"id": a.id, "name": a.name, "kind": a.kind, "driver": a.driver, "address": json.loads(a.address or "{}"),
            "max_runtime_s": a.max_runtime_s, "enabled": a.enabled, "feedback_sensor_id": a.feedback_sensor_id,
            "interlocks": json.loads(a.interlocks or "{}")}


def reload_engines(request: Request) -> None:
    request.app.state.engine.reload()
    request.app.state.climate.reload()


def _engine_for(request: Request, kind: str):
    return request.app.state.engine if kind in IRRIGATION_KINDS else request.app.state.climate


def _zone(z: Zone) -> dict:
    d = {c.name: getattr(z, c.name) for c in Zone.__table__.columns}
    d["moisture_sensor_ids"] = json.loads(z.moisture_sensor_ids or "[]")
    d["schedule"] = json.loads(z.schedule or "[]")
    return d


@router.get("/irrigation/setup")
def setup(request: Request):
    with _db(request).session() as s:
        return {"actuators": [_act(a) for a in s.scalars(select(Actuator).where(Actuator.kind.in_(IRRIGATION_KINDS))
                                                         .order_by(Actuator.id))],
                "tanks": [{c.name: getattr(t, c.name) for c in Tank.__table__.columns}
                          for t in s.scalars(select(Tank).order_by(Tank.id))],
                "zones": [_zone(z) for z in s.scalars(select(Zone).order_by(Zone.id))],
                "output_drivers": request.app.state.outputs.describe(),
                "settings": request.app.state.engine.cfg.g.model_dump()}


@router.get("/irrigation/status")
def status(request: Request):
    return _eng(request).status()


@router.put("/irrigation/settings")
def put_settings(g: IrrigationSettings, request: Request):
    for sid, what in ((g.leak_sensor_id, "leak sensor"),):
        _sensor_exists(_db(request), sid, what)
    save_settings(_db(request), g)
    _eng(request).reload()
    events.log_event(_db(request), "info", "irrigation",
                     f"Irrigation settings changed (automatic irrigation {'ON' if g.auto_enabled else 'OFF'})")
    return g.model_dump()


# ---------------------------------------------------------------- actuators

class ActuatorIn(BaseModel):
    id: str = Field(pattern=ID)
    name: str = Field(min_length=1, max_length=120)
    kind: OutputKind
    driver: str
    address: dict = {}
    max_runtime_s: int = Field(ge=1, le=604800, description="mandatory hard ceiling")
    enabled: bool = True
    feedback_sensor_id: str | None = None
    interlocks: dict = {}


def validate_interlocks(body: ActuatorIn, request: Request) -> dict:
    il = dict(body.interlocks or {})
    allowed = {"requires_on", "forbids_on", "min_on_s", "min_off_s", "stop_if", "windows_max_open_pct"}
    if set(il) - allowed:
        raise HTTPException(422, f"unknown interlock keys: {sorted(set(il) - allowed)}")
    if il and body.kind in IRRIGATION_KINDS:
        raise HTTPException(422, "equipment interlocks apply to climate outputs only")
    if body.kind in IRRIGATION_KINDS and body.max_runtime_s > 14400:
        raise HTTPException(422, "irrigation outputs are limited to 4 hours maximum runtime")
    if body.kind in ("heater", "co2"):
        si = il.get("stop_if")
        if not isinstance(si, dict) or not si.get("sensor_id") or not isinstance(si.get("above"), (int, float)):
            raise HTTPException(422, f"a {body.kind} output needs a software safety limit: "
                                     'interlocks.stop_if = {"sensor_id": ..., "above": number}')
    with _db(request).session() as s:
        ids = {a.id for a in s.scalars(select(Actuator))}
    for key in ("requires_on", "forbids_on"):
        for other in il.get(key, []):
            if other == body.id or other not in ids:
                raise HTTPException(422, f"interlocks.{key}: unknown or self output '{other}'")
    for key in ("min_on_s", "min_off_s"):
        if key in il and (not isinstance(il[key], (int, float)) or il[key] < 0):
            raise HTTPException(422, f"interlocks.{key} must be >= 0")
    pct = il.get("windows_max_open_pct")
    if "windows_max_open_pct" in il and not (isinstance(pct, (int, float)) and 0 <= pct <= 100):
        raise HTTPException(422, "interlocks.windows_max_open_pct must be 0-100")
    if il.get("stop_if"):
        _sensor_exists(_db(request), il["stop_if"]["sensor_id"], "stop_if")
    return il


def _validate_actuator(body: ActuatorIn, request: Request, existing: str | None) -> dict:
    reg = request.app.state.outputs
    try:
        drv = reg.get(body.driver)
        addr = drv.validate_address(body.address, body.kind)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(422, f"invalid address: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, str(exc)) from exc
    _sensor_exists(_db(request), body.feedback_sensor_id, "feedback")
    body.interlocks = validate_interlocks(body, request)
    key = drv.conflict_key(addr, body.kind)
    if key is not None:
        with _db(request).session() as s:
            for o in s.scalars(select(Actuator).where(Actuator.driver == body.driver)):
                if o.id != existing and drv.conflict_key(json.loads(o.address), o.kind) == key:
                    raise HTTPException(409, f"output address already used by '{o.id}'")
    return addr


@router.post("/actuators", status_code=201)
def create_actuator(body: ActuatorIn, request: Request):
    addr = _validate_actuator(body, request, None)
    with _db(request).session() as s:
        if s.get(Actuator, body.id):
            raise HTTPException(409, "id already exists")
        s.add(Actuator(id=body.id, name=body.name, kind=body.kind, driver=body.driver, address=json.dumps(addr),
                       max_runtime_s=body.max_runtime_s, enabled=body.enabled,
                       feedback_sensor_id=body.feedback_sensor_id, interlocks=json.dumps(body.interlocks)))
    reload_engines(request)
    events.log_event(_db(request), "info", "irrigation", f"Output '{body.id}' ({body.kind}) added")
    return {"id": body.id}


@router.put("/actuators/{act_id}")
async def update_actuator(act_id: str, body: ActuatorIn, request: Request):
    if body.id != act_id:
        raise HTTPException(422, "id cannot be changed")
    addr = _validate_actuator(body, request, act_id)
    if act_id in _eng(request).on or act_id in request.app.state.climate.on:
        raise HTTPException(409, "switch the output off before editing it")
    with _db(request).session() as s:
        a = s.get(Actuator, act_id)
        if a is None:
            raise HTTPException(404, "not found")
        a.name, a.kind, a.driver, a.address = body.name, body.kind, body.driver, json.dumps(addr)
        a.max_runtime_s, a.enabled, a.feedback_sensor_id = body.max_runtime_s, body.enabled, body.feedback_sensor_id
        a.interlocks = json.dumps(body.interlocks)
    reload_engines(request)
    return {"ok": True}


@router.delete("/actuators/{act_id}")
def delete_actuator(act_id: str, request: Request):
    if act_id in _eng(request).on or act_id in request.app.state.climate.on:
        raise HTTPException(409, "switch the output off first")
    with _db(request).session() as s:
        a = s.get(Actuator, act_id)
        if a is None:
            raise HTTPException(404, "not found")
        used = [z.id for z in s.scalars(select(Zone)) if act_id in (z.valve_id, z.pump_id)]
        from app.core.models import ClimateRule, LightProgram, Window
        used += [w.id for w in s.scalars(select(Window)) if act_id in (w.open_output_id, w.close_output_id)]
        used += [lp.id for lp in s.scalars(select(LightProgram)) if act_id in json.loads(lp.output_ids or "[]")]
        used += [r.id for r in s.scalars(select(ClimateRule))
                 if f'"{act_id}"' in (r.actions or "") or f'"{act_id}"' in (r.conditions or "")]
        if used:
            raise HTTPException(409, f"used by: {', '.join(used)}")
        s.delete(a)
    reload_engines(request)
    return {"ok": True}


class CommandIn(BaseModel):
    state: Literal["on", "off"]
    duration_s: float | None = Field(None, gt=0)


@router.post("/actuators/{act_id}/command")
async def command(act_id: str, body: CommandIn, request: Request):
    """Manual control. Interlocks and the output's hard runtime limit still apply."""
    with _db(request).session() as s:
        a = s.get(Actuator, act_id)
        kind = a.kind if a else "valve"
    eng = _engine_for(request, kind)
    if kind in IRRIGATION_KINDS:
        ok, msg = await eng.hold(act_id, body.state == "on", body.duration_s, eng.now())
    else:
        ok, msg = await eng.hold_output(act_id, body.state == "on", body.duration_s, eng.now())
    if not ok:
        raise HTTPException(409, msg)
    return {"ok": True, "detail": msg}


# -------------------------------------------------------------------- tanks

class TankIn(BaseModel):
    id: str = Field(pattern=ID)
    name: str = Field(min_length=1, max_length=120)
    level_sensor_id: str | None = None
    float_sensor_id: str | None = None
    min_level_pct: float = Field(15.0, ge=0, le=100)


@router.post("/irrigation/tanks", status_code=201)
def create_tank(body: TankIn, request: Request):
    return _upsert_tank(body, request, True)


@router.put("/irrigation/tanks/{tank_id}")
def update_tank(tank_id: str, body: TankIn, request: Request):
    if body.id != tank_id:
        raise HTTPException(422, "id cannot be changed")
    return _upsert_tank(body, request, False)


def _upsert_tank(body: TankIn, request: Request, create: bool):
    if not body.level_sensor_id and not body.float_sensor_id:
        raise HTTPException(422, "a tank needs a level sensor and/or a float switch sensor")
    _sensor_exists(_db(request), body.level_sensor_id, "level sensor")
    _sensor_exists(_db(request), body.float_sensor_id, "float sensor")
    with _db(request).session() as s:
        t = s.get(Tank, body.id)
        if create and t:
            raise HTTPException(409, "id already exists")
        if not create and t is None:
            raise HTTPException(404, "not found")
        t = t or Tank(id=body.id)
        t.name, t.level_sensor_id, t.float_sensor_id = body.name, body.level_sensor_id, body.float_sensor_id
        t.min_level_pct = body.min_level_pct
        s.merge(t)
    _eng(request).reload()
    return {"id": body.id}


@router.delete("/irrigation/tanks/{tank_id}")
def delete_tank(tank_id: str, request: Request):
    with _db(request).session() as s:
        t = s.get(Tank, tank_id)
        if t is None:
            raise HTTPException(404, "not found")
        used = [z.id for z in s.scalars(select(Zone)) if z.tank_id == tank_id]
        if used:
            raise HTTPException(409, f"used by zone(s): {', '.join(used)}")
        s.delete(t)
    _eng(request).reload()
    return {"ok": True}


# -------------------------------------------------------------------- zones

class ScheduleEntry(BaseModel):
    days: list[int] = Field(min_length=1)
    time: str
    duration_s: int = Field(gt=0, le=14400)

    @field_validator("days")
    @classmethod
    def _days(cls, v):
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("days are 0 (Monday) to 6 (Sunday)")
        return sorted(set(v))

    @field_validator("time")
    @classmethod
    def _time(cls, v):
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
            raise ValueError("time must be HH:MM (24 h)")
        return v


class ZoneIn(BaseModel):
    id: str = Field(pattern=ID)
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["soil", "hydroponic"]
    valve_id: str
    pump_id: str | None = None
    tank_id: str | None = None
    flow_sensor_id: str | None = None
    enabled: bool = True
    auto_enabled: bool = False
    max_duration_s: int = Field(ge=1, le=14400)
    default_duration_s: int = Field(300, ge=1, le=14400)
    min_interval_s: int = Field(3600, ge=0)
    expected_flow_lpm: float | None = Field(None, gt=0)
    min_flow_lpm: float | None = Field(None, ge=0)
    max_flow_lpm: float | None = Field(None, gt=0)
    flow_grace_s: int = Field(20, ge=0, le=600)
    moisture_sensor_ids: list[str] = []
    moisture_start_below: float | None = Field(None, ge=0, le=100)
    moisture_stop_at: float | None = Field(None, ge=0, le=100)
    schedule: list[ScheduleEntry] = []


def _validate_zone(body: ZoneIn, request: Request) -> None:
    db = _db(request)
    if body.default_duration_s > body.max_duration_s:
        raise HTTPException(422, "default duration cannot exceed the maximum duration")
    if (body.min_flow_lpm is not None and body.max_flow_lpm is not None and body.min_flow_lpm >= body.max_flow_lpm):
        raise HTTPException(422, "min flow must be below max flow")
    if (body.moisture_start_below is not None and body.moisture_stop_at is not None
            and body.moisture_stop_at <= body.moisture_start_below):
        raise HTTPException(422, "moisture stop level must be above the start level")
    if (body.min_flow_lpm is not None or body.max_flow_lpm is not None) and not body.flow_sensor_id:
        raise HTTPException(422, "flow limits need a flow sensor")
    if body.moisture_start_below is not None and not body.moisture_sensor_ids:
        raise HTTPException(422, "moisture trigger needs at least one moisture sensor")
    with db.session() as s:
        v = s.get(Actuator, body.valve_id)
        if v is None or v.kind != "valve":
            raise HTTPException(422, "valve_id must be an existing output of kind 'valve'")
        if body.pump_id:
            p = s.get(Actuator, body.pump_id)
            if p is None or p.kind != "pump":
                raise HTTPException(422, "pump_id must be an existing output of kind 'pump'")
            if not body.tank_id:
                raise HTTPException(422, "a zone with a pump needs a tank (water-level interlock)")
        if body.tank_id and s.get(Tank, body.tank_id) is None:
            raise HTTPException(422, f"unknown tank '{body.tank_id}'")
    for sid in [body.flow_sensor_id, *body.moisture_sensor_ids]:
        _sensor_exists(db, sid, "zone sensor")


def _write_zone(z: Zone, b: ZoneIn) -> None:
    for k in ("name", "kind", "valve_id", "pump_id", "tank_id", "flow_sensor_id", "enabled", "auto_enabled",
              "max_duration_s", "default_duration_s", "min_interval_s", "expected_flow_lpm", "min_flow_lpm",
              "max_flow_lpm", "flow_grace_s", "moisture_start_below", "moisture_stop_at"):
        setattr(z, k, getattr(b, k))
    z.moisture_sensor_ids = json.dumps(b.moisture_sensor_ids)
    z.schedule = json.dumps([e.model_dump() for e in b.schedule])


@router.post("/irrigation/zones", status_code=201)
def create_zone(body: ZoneIn, request: Request):
    _validate_zone(body, request)
    with _db(request).session() as s:
        if s.get(Zone, body.id):
            raise HTTPException(409, "id already exists")
        z = Zone(id=body.id)
        _write_zone(z, body)
        s.add(z)
    _eng(request).reload()
    return {"id": body.id}


@router.put("/irrigation/zones/{zone_id}")
def update_zone(zone_id: str, body: ZoneIn, request: Request):
    if body.id != zone_id:
        raise HTTPException(422, "id cannot be changed")
    if zone_id in _eng(request).jobs:
        raise HTTPException(409, "stop the zone before editing it")
    _validate_zone(body, request)
    with _db(request).session() as s:
        z = s.get(Zone, zone_id)
        if z is None:
            raise HTTPException(404, "not found")
        _write_zone(z, body)
    _eng(request).reload()
    return {"ok": True}


@router.delete("/irrigation/zones/{zone_id}")
def delete_zone(zone_id: str, request: Request):
    if zone_id in _eng(request).jobs:
        raise HTTPException(409, "stop the zone first")
    with _db(request).session() as s:
        z = s.get(Zone, zone_id)
        if z is None:
            raise HTTPException(404, "not found")
        s.delete(z)
    _eng(request).reload()
    return {"ok": True}


class RunIn(BaseModel):
    duration_s: float | None = Field(None, gt=0)


@router.post("/irrigation/zones/{zone_id}/run")
async def run_zone(zone_id: str, body: RunIn, request: Request):
    ok, msg = await _eng(request).start_zone(zone_id, body.duration_s, "manual", _eng(request).now())
    if not ok:
        raise HTTPException(409, msg)
    return {"ok": True, "detail": msg}


@router.post("/irrigation/zones/{zone_id}/stop")
async def stop_zone(zone_id: str, request: Request):
    now = _eng(request).now()
    if not _eng(request).stop_zone(zone_id, now):
        raise HTTPException(409, "zone is not running")
    await _eng(request).tick(now)
    return {"ok": True}


# --------------------------------------------------------- history/water

@router.get("/irrigation/history")
def history(request: Request, days: int = 30):
    since = int(time.time() - max(1, min(days, 366)) * 86400)
    with _db(request).session() as s:
        runs = s.scalars(select(IrrigationRun).where(IrrigationRun.start_ts >= since)
                         .order_by(IrrigationRun.id.desc()).limit(500)).all()
    daily: dict[str, dict] = defaultdict(lambda: {"runs": 0, "seconds": 0, "measured_l": 0.0, "estimated_l": 0.0})
    for r in runs:
        d = daily[time.strftime("%Y-%m-%d", time.localtime(r.start_ts))]
        d["runs"] += 1
        d["seconds"] += r.actual_s or 0
        d["measured_l"] += r.volume_l or 0
        d["estimated_l"] += r.volume_estimate_l or 0
    return {"runs": [{"id": r.id, "zone_id": r.zone_id, "source": r.source, "start_ts": r.start_ts,
                      "end_ts": r.end_ts, "planned_s": r.planned_s, "actual_s": r.actual_s,
                      "volume_l": r.volume_l, "volume_estimate_l": r.volume_estimate_l,
                      "end_reason": r.end_reason} for r in runs],
            "daily": [{"date": k, **{kk: round(vv, 2) for kk, vv in v.items()}} for k, v in sorted(daily.items())],
            "note": "Measured litres come from flow sensors only; estimated litres = your expected flow x run time."}


# ------------------------------------------------------- safety endpoints

@router.get("/safety")
def safety(request: Request):
    return commissioning.status(_db(request), _eng(request))


class ConfirmIn(BaseModel):
    confirm: bool = False


@router.post("/safety/estop")
async def estop(request: Request):
    now = _eng(request).now()
    await _eng(request).set_estop(now)
    await request.app.state.climate.tick(now)  # reads the latch: everything off, windows stopped
    return {"estop": True}


@router.post("/safety/estop/reset")
def estop_reset(body: ConfirmIn, request: Request):
    if not body.confirm:
        raise HTTPException(422, "confirm that the cause has been found and it is safe to restart")
    _eng(request).reset_estop()
    return {"estop": False}


def _cctx(request: Request) -> commissioning.Ctx:
    a = request.app.state
    return commissioning.Ctx(a.db, a.ingest, a.settings, a.ctx)


def _gate_changed(request: Request) -> None:
    request.app.state.engine.invalidate_gate()
    request.app.state.climate.invalidate_gate()


@router.post("/safety/checks/{check_id}/run")
def run_check(check_id: str, request: Request):
    if check_id not in commissioning.AUTO:
        raise HTTPException(422, "this check has no automatic test")
    r = commissioning.run_auto(check_id, _cctx(request))
    _gate_changed(request)
    return r


class AttestIn(BaseModel):
    note: str


@router.post("/safety/checks/{check_id}/attest")
def attest(check_id: str, body: AttestIn, request: Request):
    if check_id not in commissioning.BY_ID:
        raise HTTPException(404, "unknown check")
    try:
        commissioning.attest(_db(request), check_id, body.note)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _gate_changed(request)
    events.log_event(_db(request), "warning", "safety", f"Check '{check_id}' attested by user: {body.note[:120]}")
    return {"ok": True}


@router.delete("/safety/checks/{check_id}")
def revoke(check_id: str, request: Request):
    if check_id not in commissioning.BY_ID:
        raise HTTPException(404, "unknown check")
    commissioning.revoke(_db(request), check_id)
    _gate_changed(request)
    return {"ok": True}


@router.post("/alerts/{alert_id}/clear")
def clear_alert(alert_id: int, request: Request):
    with _db(request).session() as s:
        a = s.get(Alert, alert_id)
        if a is None:
            raise HTTPException(404, "alert not found")
        a.active, a.acknowledged = False, True
    return {"ok": True}
