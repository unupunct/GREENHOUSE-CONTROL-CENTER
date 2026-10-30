"""Climate engine: rules (visual rule builder), motorised windows, lighting
programs (photoperiod / DLI), equipment interlocks.

Same philosophy as the irrigation engine: express what should be ON, filter it
through interlocks, enforce hard runtime ceilings, treat uncertainty as OFF,
force everything off at start-up/shut-down and on e-stop.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.automation import climate_rules as cr
from app.core.db import Database
from app.core.models import (
    Actuator,
    AppSetting,
    ClimateRule,
    DailyStat,
    LightProgram,
    Window,
)
from app.hal.outputs import CLIMATE_KINDS, OutputRegistry, OutputSpec
from app.services import climate as climate_calc
from app.services import events

log = logging.getLogger(__name__)
SETTINGS_KEY = "climate"


class ClimateSettings(BaseModel):
    auto_enabled: bool = False
    sensor_max_age_s: float = Field(30.0, gt=0, le=600)


def load_settings(db: Database) -> ClimateSettings:
    with db.session() as s:
        row = s.get(AppSetting, SETTINGS_KEY)
        return ClimateSettings.model_validate(json.loads(row.value)) if row else ClimateSettings()


def save_settings(db: Database, g: ClimateSettings) -> None:
    with db.session() as s:
        row = s.get(AppSetting, SETTINGS_KEY)
        payload = g.model_dump_json()
        if row is None:
            s.add(AppSetting(key=SETTINGS_KEY, value=payload, updated_at=int(time.time())))
        else:
            row.value, row.updated_at = payload, int(time.time())


@dataclass
class Hold:
    until: float
    state: str  # on | off


@dataclass
class WState:
    pos: float | None = None
    moving: str | None = None
    started: float = 0.0
    from_pos: float = 0.0
    duration: float = 0.0
    end_pos: float = 0.0
    last_stop: float = -1e18
    hazard: str | None = None
    homing: bool = False


@dataclass
class _Cfg:
    acts: dict[str, dict] = field(default_factory=dict)
    rules: dict[str, dict] = field(default_factory=dict)
    windows: dict[str, dict] = field(default_factory=dict)
    lights: dict[str, dict] = field(default_factory=dict)
    g: ClimateSettings = field(default_factory=ClimateSettings)


class ClimateEngine:
    def __init__(self, db: Database, outputs: OutputRegistry, ingest, estop_fn=lambda: False,
                 gate_fn=lambda: False, level_fn=lambda: "full") -> None:
        self.db, self.outputs, self.ingest = db, outputs, ingest
        self.estop_fn, self.gate_fn, self.level_fn = estop_fn, gate_fn, level_fn
        self._gate_memo = None
        self.clock = time.time
        self.cfg = _Cfg()
        self.loaded = False
        self.on: dict[str, float] = {}
        self.last_off: dict[str, float] = {}
        self.blocked_until: dict[str, float] = {}
        self.holds: dict[str, Hold] = {}
        self.win_holds: dict[str, tuple[float, float]] = {}
        self.rule_state: dict[str, cr.RuleState] = {}
        self.latched: dict[tuple, bool] = {}
        self.win: dict[str, WState] = {}
        self.lstate: dict[str, bool] = {}
        self.stats_date = ""
        self.stats: dict[str, float] = {}
        self._stats_flush = 0.0
        self._last_tick: float | None = None
        self._refusal_logged: dict[str, str] = {}
        self._task = None

    def now(self) -> float:
        return self.clock()

    # ------------------------------------------------------------ config
    def reload(self) -> None:
        with self.db.session() as s:
            acts = {a.id: dict(id=a.id, name=a.name, kind=a.kind, driver=a.driver, address=json.loads(a.address or "{}"),
                               max_runtime_s=a.max_runtime_s, enabled=a.enabled,
                               interlocks=json.loads(a.interlocks or "{}"))
                    for a in s.scalars(select(Actuator).where(Actuator.kind.in_(CLIMATE_KINDS)))}
            rules = {}
            for r in s.scalars(select(ClimateRule)):
                d = {c.name: getattr(r, c.name) for c in ClimateRule.__table__.columns}
                d["conditions"], d["actions"] = json.loads(r.conditions or "[]"), json.loads(r.actions or "[]")
                rules[r.id] = d
            wins = {w.id: {c.name: getattr(w, c.name) for c in Window.__table__.columns} for w in s.scalars(select(Window))}
            lights = {}
            for lp in s.scalars(select(LightProgram)):
                d = {c.name: getattr(lp, c.name) for c in LightProgram.__table__.columns}
                d["output_ids"] = json.loads(lp.output_ids or "[]")
                lights[lp.id] = d
            saved = {r.key: json.loads(r.value) for r in s.scalars(select(AppSetting)) if r.key.startswith("window_pos:")}
        self.cfg = _Cfg(acts, rules, wins, lights, load_settings(self.db))
        for wid in wins:
            st = self.win.setdefault(wid, WState())
            if st.moving is None and st.pos is None:
                st.pos = saved.get(f"window_pos:{wid}")
        for rid in list(self.rule_state):
            if rid not in rules:
                del self.rule_state[rid]
        self.loaded = True
        self._gate_memo = None

    # ----------------------------------------------------------- helpers
    def _val(self, sid: str | None, now: float) -> float | None:
        """Fresh value or None."""
        if not sid:
            return None
        lv = self.ingest.latest.get(sid)
        if lv is None or now - lv.ts > self.cfg.g.sensor_max_age_s:
            return None
        return lv.value

    def _save_pos(self, wid: str, pos: float | None) -> None:
        with self.db.session() as s:
            key = f"window_pos:{wid}"
            row = s.get(AppSetting, key)
            payload = json.dumps(pos)
            if row is None:
                s.add(AppSetting(key=key, value=payload, updated_at=int(time.time())))
            else:
                row.value, row.updated_at = payload, int(time.time())

    def _gate(self) -> bool:
        now = self.now()
        if self._gate_memo is None or now - self._gate_memo[0] >= 2.0 or now < self._gate_memo[0]:
            self._gate_memo = (now, bool(self.gate_fn()))
        return self._gate_memo[1]

    def invalidate_gate(self) -> None:
        self._gate_memo = None

    def auto_allowed(self) -> tuple[bool, str]:
        if self.estop_fn():
            return False, "emergency stop latched"
        if not self.cfg.g.auto_enabled:
            return False, "automatic climate control is switched off"
        if self.level_fn() == "monitor_only":
            return False, "greenhouse automation level is 'monitor only'"
        if not self._gate():
            return False, "commissioning checks have not all passed"
        return True, "ok"

    def _open_max(self) -> float | None:
        vents = [w for w in self.cfg.windows.values() if w["kind"] == "vent" and w["enabled"]]
        if not vents:
            return None
        return max((self.win[w["id"]].pos if self.win[w["id"]].pos is not None else 100.0) for w in vents)

    # -------------------------------------------------------- conditions
    def _cond(self, rid: str, idx: int, c: dict, now: float) -> bool | None:
        t = c["type"]
        if t in ("sensor", "vpd"):
            if t == "sensor":
                vals = [self._val(s, now) for s in c["sensors"]]
                if not vals or any(v is None for v in vals):
                    return None
                agg = c.get("agg", "mean")
                value = min(vals) if agg == "min" else max(vals) if agg == "max" else sum(vals) / len(vals)
            else:
                ts = [self._val(s, now) for s in c["temp_sensors"]]
                hs = [self._val(s, now) for s in c["rh_sensors"]]
                if not ts or not hs or any(v is None for v in ts + hs):
                    return None
                value = climate_calc.vpd_kpa(sum(ts) / len(ts), sum(hs) / len(hs))
            st = cr.threshold_state(c["op"], c["on"], c.get("off", c["on"]), value, self.latched.get((rid, idx), False))
            if st is not None:
                self.latched[(rid, idx)] = st
            return st
        lt = time.localtime(now)
        if t == "time":
            return cr.in_time_window(lt.tm_hour * 60 + lt.tm_min, c["start"], c["end"])
        if t == "month":
            return lt.tm_mon in c["months"]
        if t == "output":
            return (c["output_id"] in self.on) == (c.get("state", "on") == "on")
        return None

    def _eval_rules(self, now: float) -> tuple[list, list]:
        out_wants, win_wants = [], []
        for rid, r in self.cfg.rules.items():
            rs = self.rule_state.setdefault(rid, cr.RuleState())
            if not r["enabled"]:
                if rs.active:
                    rs.active = False
                continue
            states = [self._cond(rid, i, c, now) for i, c in enumerate(r["conditions"])]
            raw = cr.combine(r["match"], states)
            ev = cr.step_rule(rs, raw, now, cr.Timing(r["on_delay_s"], r["off_delay_s"], r["min_on_s"],
                                                      r["min_off_s"], r["max_on_s"], r["cooldown_s"], r["on_fault"]))
            if ev == "activated":
                events.log_event(self.db, "info", "climate", f"Rule '{rid}' ({r['name']}) activated")
                if r["notify"]:
                    events.raise_alert(self.db, "warning", "rule_notify", rid, f"Rule '{r['name']}' activated")
            elif ev in ("released", "forced_release"):
                events.log_event(self.db, "info" if ev == "released" else "warning", "climate",
                                 f"Rule '{rid}' ({r['name']}) {'released' if ev == 'released' else 'stopped at its maximum on-time'}")
            if rs.active:
                for a in r["actions"]:
                    if "window_id" in a:
                        win_wants.append((r["priority"], a["window_id"], float(a["position_pct"])))
                    else:
                        out_wants.append((r["priority"], a["output_id"], a["state"]))
        return out_wants, win_wants

    # ---------------------------------------------------------- lighting
    def _in_light_window(self, lp: dict, now: float) -> bool:
        lt = time.localtime(now)
        h, m = map(int, lp["start_time"].split(":"))
        end_min = int(round((h * 60 + m + lp["photoperiod_h"] * 60))) % 1440
        end = f"{end_min // 60:02d}:{end_min % 60:02d}"
        if lp["photoperiod_h"] >= 24:
            return True
        return cr.in_time_window(lt.tm_hour * 60 + lt.tm_min, lp["start_time"], end)

    def _roll_stats(self, now: float) -> None:
        d = time.strftime("%Y-%m-%d", time.localtime(now))
        if d != self.stats_date:
            self._flush_stats(force=True)
            self.stats_date = d
            with self.db.session() as s:
                self.stats = {r.key: r.value for r in s.scalars(select(DailyStat).where(DailyStat.date == d))}
            self.lstate = {}

    def _flush_stats(self, force: bool = False) -> None:
        if not self.stats_date or (not force and self.clock() - self._stats_flush < 60):
            return
        with self.db.session() as s:
            for k, v in self.stats.items():
                s.merge(DailyStat(date=self.stats_date, key=k, value=round(v, 4)))
        self._stats_flush = self.clock()

    def _lighting(self, now: float, dt: float, auto: bool) -> list[tuple[int, str, str]]:
        wants = []
        for lid, lp in self.cfg.lights.items():
            if not lp["enabled"]:
                continue
            ppfd = self._val(lp["ppfd_sensor_id"], now)
            dt = dt if dt <= 10 else 0.0  # a long gap (outage, suspend) is not integrated
            if ppfd is not None and dt:
                self.stats["dli_mol"] = self.stats.get("dli_mol", 0.0) + ppfd * dt / 1e6
            power = self._val(lp["power_sensor_id"], now)
            if power is not None and dt:
                self.stats["light_kwh"] = self.stats.get("light_kwh", 0.0) + power * dt / 3.6e6
            if not auto:
                continue
            want = False
            if self._in_light_window(lp, now):
                if lp["mode"] == "photoperiod":
                    want = True
                elif lp["mode"] == "dli" and ppfd is not None and lp["dli_target"] is not None:
                    if self.stats.get("dli_mol", 0.0) < lp["dli_target"]:
                        want = cr.threshold_state("<", lp["on_below_ppfd"], lp["off_above_ppfd"], ppfd,
                                                  self.lstate.get(lid, False)) or False
                    self.lstate[lid] = want
            for oid in lp["output_ids"]:
                wants.append((100, oid, "on" if want else "off"))
            if want and any(o in self.on for o in lp["output_ids"]):
                self.stats["light_on_s"] = self.stats.get("light_on_s", 0.0) + dt
        return wants

    # ----------------------------------------------------------- windows
    def _window_target(self, wid: str, w: dict, win_best: dict, auto: bool, now: float) -> tuple[float | None, str | None]:
        st = self.win[wid]
        haz = None
        if w["kind"] == "vent":
            haz = cr.hazard(rain=self._val(w["rain_sensor_id"], now), rain_configured=bool(w["rain_sensor_id"]),
                            wind=self._val(w["wind_sensor_id"], now), wind_configured=bool(w["wind_sensor_id"]),
                            wind_max=w["wind_max_ms"])
        if st.hazard != haz:
            if haz:
                events.log_event(self.db, "warning", "climate", f"Window '{wid}' closing: {haz}")
            st.hazard = haz
        if haz and (auto or wid in self.win_holds or st.moving):
            return 0.0, haz
        h = self.win_holds.get(wid)
        if h and h[0] > now:
            return h[1], None
        if auto:
            return (win_best[wid][1] if wid in win_best else 0.0), None  # default: closed
        return None, None

    async def _windows(self, now: float, win_best: dict, auto: bool) -> set[str]:
        motors: set[str] = set()
        estop = self.estop_fn()
        for wid, w in self.cfg.windows.items():
            st = self.win[wid]
            o_open, o_close = w["open_output_id"], w["close_output_id"]
            if not w["enabled"] or o_open not in self.cfg.acts or o_close not in self.cfg.acts:
                continue
            if estop:
                self._stop_window(wid, now)
                continue
            target, _ = self._window_target(wid, w, win_best, auto, now)
            if st.moving:
                elapsed = now - st.started
                est = cr.estimate_position(st.from_pos, st.moving, elapsed, w["travel_time_s"])
                limit_id = w["open_limit_sensor_id"] if st.moving == "open" else w["closed_limit_sensor_id"]
                limit_hit = limit_id and self._val(limit_id, now) is not None and self._val(limit_id, now) >= 0.5
                wrong_way = (not st.homing) and target is not None and (
                    (st.moving == "open" and target < est - 0.5) or (st.moving == "close" and target > est + 0.5))
                if elapsed >= st.duration or limit_hit or target is None or wrong_way:
                    reached = elapsed >= st.duration or limit_hit
                    st.pos = st.end_pos if reached else est
                    if limit_hit:
                        st.pos = 100.0 if st.moving == "open" else 0.0
                    self._stop_window(wid, now, set_pos=st.pos)
                else:
                    motors.add(o_open if st.moving == "open" else o_close)
                continue
            if target is None or now - st.last_stop < w["min_rest_s"]:
                continue
            if now < max(self.blocked_until.get(o_open, 0), self.blocked_until.get(o_close, 0)):
                continue  # a motor output was forced off recently: leave it alone
            plan = cr.move_plan(st.pos, target, w["travel_time_s"], w["min_step_pct"])
            if plan is None:
                continue
            direction, run_s, end_pos = plan
            st.moving, st.started, st.from_pos = direction, now, 100.0 if st.pos is None and direction == "close" else (st.pos or 0.0)
            st.duration, st.end_pos, st.homing = run_s, end_pos, st.pos is None
            motors.add(o_open if direction == "open" else o_close)
        return motors

    def _stop_window(self, wid: str, now: float, set_pos: float | None = -1.0) -> None:
        st = self.win[wid]
        if st.moving and set_pos == -1.0:  # emergency/other stop: estimate from elapsed time
            w = self.cfg.windows[wid]
            st.pos = cr.estimate_position(st.from_pos, st.moving, now - st.started, w["travel_time_s"]) if not st.homing else None
        st.moving, st.last_stop, st.homing = None, now, False
        self._save_pos(wid, st.pos)

    # ----------------------------------------------------------- manual
    async def hold_output(self, oid: str, on: bool, duration_s: float | None, now: float) -> tuple[bool, str]:
        if not self.loaded:
            self.reload()
        a = self.cfg.acts.get(oid)
        if a is None or not a["enabled"] or a["kind"] == "motor":
            return False, "unknown output (windows are controlled as windows)"
        if on and self.estop_fn():
            return False, "emergency stop is latched"
        dur = min(float(duration_s or (a["max_runtime_s"] if on else 600)), float(a["max_runtime_s"] if on else 86400))
        if on:
            ok, why = cr.allowed_outputs({oid: 1000}, {k: v["interlocks"] for k, v in self.cfg.acts.items()}, set(self.on),
                                         now=now, last_off=self.last_off, blocked_until=self.blocked_until,
                                         sensor=lambda s: self._val(s, now), window_open_max_pct=self._open_max())
            if oid not in ok:
                return False, why.get(oid, "refused")
        self.holds[oid] = Hold(now + dur, "on" if on else "off")
        want = set(self.on)
        want.add(oid) if on else want.discard(oid)
        await self._reconcile(now, want)
        return True, f"{'on' if on else 'forced off'} for up to {dur:.0f}s"

    def release_output(self, oid: str) -> None:
        self.holds.pop(oid, None)

    def hold_window(self, wid: str, pos: float, duration_s: float, now: float) -> tuple[bool, str]:
        if not self.loaded:
            self.reload()
        w = self.cfg.windows.get(wid)
        if w is None or not w["enabled"]:
            return False, "unknown or disabled window"
        if self.estop_fn():
            return False, "emergency stop is latched"
        if not 0 <= pos <= 100:
            return False, "position must be 0-100"
        self.win_holds[wid] = (now + duration_s, pos)
        return True, f"moving to {pos:g}% (held {duration_s:.0f}s)"

    def release_window(self, wid: str) -> None:
        self.win_holds.pop(wid, None)

    # -------------------------------------------------------------- tick
    @property
    def estop(self) -> bool:
        return bool(self.estop_fn())

    async def tick(self, now: float | None = None) -> None:
        now = self.now() if now is None else now
        if not self.loaded:
            self.reload()
        dt = 0.0 if self._last_tick is None else max(0.0, now - self._last_tick)
        self._last_tick = now
        self._roll_stats(now)
        estop = self.estop_fn()
        if estop:
            self.holds.clear()
            self.win_holds.clear()
        for oid, since in list(self.on.items()):  # hard runtime ceiling
            a = self.cfg.acts.get(oid)
            if a is None or now - since > a["max_runtime_s"]:
                self._runtime_cut(oid, now)
        auto = self.auto_allowed()[0]
        out_wants, win_wants = self._eval_rules(now) if auto else ([], [])
        out_wants += self._lighting(now, dt, auto)
        best = cr.resolve_outputs(out_wants)
        win_best = cr.resolve_windows(win_wants)
        want_on = {o: p for o, (p, s) in best.items() if s == "on" and o in self.cfg.acts and self.cfg.acts[o]["enabled"]}
        for oid, h in list(self.holds.items()):
            if h.until <= now:
                del self.holds[oid]
            elif h.state == "on":
                want_on[oid] = 1000
            else:
                want_on.pop(oid, None)
        if estop:
            want_on = {}
        interlocks = {k: v["interlocks"] for k, v in self.cfg.acts.items()}
        allowed, reasons = cr.allowed_outputs(want_on, interlocks, set(self.on), now=now, last_off=self.last_off,
                                              blocked_until=self.blocked_until, sensor=lambda s: self._val(s, now),
                                              window_open_max_pct=self._open_max())
        for oid, why in reasons.items():
            if self._refusal_logged.get(oid) != why:
                self._refusal_logged[oid] = why
                events.log_event(self.db, "warning", "climate", f"'{oid}' not switched on: {why}")
        for oid in list(self._refusal_logged):
            if oid not in reasons:
                del self._refusal_logged[oid]
        for oid in list(self.on):  # minimum on-time (anti short-cycling) unless refused by an interlock
            il = interlocks.get(oid, {})
            if oid not in allowed and oid not in reasons and il.get("min_on_s") and not estop \
                    and now - self.on[oid] < il["min_on_s"] and self.on[oid] != float("inf"):
                allowed.add(oid)
        motors = await self._windows(now, win_best, auto)
        await self._reconcile(now, allowed | motors)
        self._flush_stats()

    def _runtime_cut(self, oid: str, now: float) -> None:
        a = self.cfg.acts.get(oid)
        self.holds.pop(oid, None)
        il = (a or {}).get("interlocks", {})
        self.blocked_until[oid] = now + max(float(il.get("min_off_s", 0)), 60.0)
        for wid, w in self.cfg.windows.items():
            if oid in (w["open_output_id"], w["close_output_id"]) and self.win[wid].moving:
                self.win[wid].moving, self.win[wid].pos, self.win[wid].last_stop = None, None, now
                self._save_pos(wid, None)
        events.log_event(self.db, "warning", "climate", f"'{oid}' forced off: maximum runtime reached")
        events.raise_alert(self.db, "warning", "max_runtime", oid, f"Output '{oid}' was forced off at its maximum runtime"
                           + (f" ({a['max_runtime_s']}s)" if a else ""))
        self.on[oid] = float("inf")

    async def _command(self, oid: str, on: bool, now: float) -> bool:
        a = self.cfg.acts.get(oid)
        if a is None:
            self.on.pop(oid, None)
            return True
        try:
            await self.outputs.get(a["driver"]).set(OutputSpec(oid, a["kind"], a["address"]), on)
        except Exception as exc:  # noqa: BLE001
            if on:
                self.blocked_until[oid] = now + 30
                events.raise_alert(self.db, "critical", "output_error", oid, f"Cannot switch '{oid}' on: {exc}")
                for wid, w in self.cfg.windows.items():
                    if oid in (w["open_output_id"], w["close_output_id"]):
                        self.win[wid].moving, self.win[wid].last_stop = None, now
            else:
                events.raise_alert(self.db, "critical", "output_stuck", oid,
                                   f"Cannot switch '{oid}' OFF ({exc}). Cut power manually. Retrying.")
            return False
        if on:
            self.on[oid] = now
            events.log_event(self.db, "info", "climate", f"'{oid}' ON")
        else:
            self.on.pop(oid, None)
            self.last_off[oid] = now
            events.clear_alert(self.db, "output_stuck", oid)
            events.log_event(self.db, "info", "climate", f"'{oid}' OFF")
        return True

    async def _reconcile(self, now: float, want: set[str]) -> None:
        for oid in list(self.on):  # OFF first (also guarantees a window motor pair is never both on)
            if oid not in want:
                await self._command(oid, False, now)
        for oid in sorted(want):
            if oid in self.on or oid not in self.cfg.acts:
                continue
            a = self.cfg.acts[oid]
            if a["kind"] == "motor":  # never energise both directions of one window
                pair = next((w for w in self.cfg.windows.values() if oid in (w["open_output_id"], w["close_output_id"])), None)
                other = None if pair is None else (pair["close_output_id"] if oid == pair["open_output_id"] else pair["open_output_id"])
                if other and other in self.on:
                    continue
            if not await self._command(oid, True, now) and a["kind"] == "motor":
                continue

    # ----------------------------------------------------------- status
    def status(self, now: float | None = None) -> dict:
        now = self.now() if now is None else now
        if not self.loaded:
            self.reload()
        ok, why = self.auto_allowed()
        return {
            "estop": self.estop_fn(), "auto_enabled": self.cfg.g.auto_enabled, "auto_allowed": ok, "auto_detail": why,
            "outputs": {o: {"on": o in self.on and self.on[o] != float("inf"), "kind": a["kind"], "name": a["name"],
                            "on_for_s": round(now - self.on[o], 1) if o in self.on and self.on[o] != float("inf") else None,
                            "override": (self.holds[o].state if o in self.holds else None),
                            "max_runtime_s": a["max_runtime_s"], "refused": self._refusal_logged.get(o)}
                        for o, a in self.cfg.acts.items()},
            "rules": [{"id": rid, "name": r["name"], "enabled": r["enabled"], "priority": r["priority"],
                       "active": self.rule_state.get(rid, cr.RuleState()).active, "generated": r["generated"]}
                      for rid, r in self.cfg.rules.items()],
            "windows": [{"id": wid, "name": w["name"], "kind": w["kind"], "enabled": w["enabled"],
                         "position_pct": self._shown_pos(wid, now),
                         "position_is_estimate": True, "moving": self.win[wid].moving, "hazard": self.win[wid].hazard,
                         "override_pct": self.win_holds[wid][1] if wid in self.win_holds and self.win_holds[wid][0] > now else None}
                        for wid, w in self.cfg.windows.items()],
            "lighting": {"date": self.stats_date, "dli_mol": round(self.stats.get("dli_mol", 0.0), 3),
                         "light_kwh": round(self.stats.get("light_kwh", 0.0), 3),
                         "light_on_h": round(self.stats.get("light_on_s", 0.0) / 3600, 2),
                         "programs": [{"id": lid, "name": lp["name"], "mode": lp["mode"],
                                       "on": any(o in self.on for o in lp["output_ids"])} for lid, lp in self.cfg.lights.items()],
                         "note": "DLI is measured by the PAR sensor and includes light from your fixtures."},
        }

    def _shown_pos(self, wid: str, now: float) -> float | None:
        st = self.win[wid]
        if st.moving and not st.homing:
            return round(cr.estimate_position(st.from_pos, st.moving, now - st.started, self.cfg.windows[wid]["travel_time_s"]), 1)
        return None if st.pos is None or st.homing else round(st.pos, 1)

    # --------------------------------------------------------- lifecycle
    async def startup(self, now: float | None = None) -> None:
        self.reload()
        now = self.now() if now is None else now
        self._roll_stats(now)
        for oid in self.cfg.acts:
            await self._command(oid, False, now)

    async def shutdown(self) -> None:
        now = self.now()
        for oid in list(self.on):
            await self._command(oid, False, now)
        self._flush_stats(force=True)

    def start(self) -> None:
        import asyncio

        async def loop():
            while True:
                try:
                    await self.tick()
                except Exception:  # noqa: BLE001
                    log.exception("climate tick failed")
                    try:
                        for oid in list(self.on):
                            await self._command(oid, False, self.now())
                    except Exception:  # noqa: BLE001
                        pass
                await asyncio.sleep(1.0)

        self._task = asyncio.create_task(loop())

    async def stop(self) -> None:
        import asyncio
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        await self.shutdown()

