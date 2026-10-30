"""Irrigation engine.

Design: jobs (zone runs) and manual holds express what should be ON; every tick
the engine reconciles real outputs with that desired set, applying interlocks
before switching anything on and hard runtime limits at all times. Outputs are
forced OFF at start-up and shut-down. Anything uncertain (missing sensor,
stale data, driver error) resolves to OFF.

Sequencing per zone: valve opens -> settle -> pump on -> run -> pump off ->
settle -> valve closes. An abort switches everything off at once.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.automation import rules
from app.core.db import Database
from app.core.models import Actuator, AppSetting, IrrigationRun, Tank, Zone
from app.hal.outputs import IRRIGATION_KINDS, OutputRegistry, OutputSpec
from app.services import events

log = logging.getLogger(__name__)
SETTINGS_KEY, ESTOP_KEY = "irrigation", "estop"


class IrrigationSettings(BaseModel):
    auto_enabled: bool = False  # master switch for schedules/moisture triggers
    max_simultaneous_zones: int = Field(1, ge=1, le=20)
    valve_settle_s: float = Field(3.0, ge=0, le=60)
    sensor_max_age_s: float = Field(20.0, gt=0, le=600)
    leak_sensor_id: str | None = None
    leak_threshold_lpm: float | None = Field(None, gt=0)
    leak_confirm_s: float = Field(60.0, ge=1, le=3600)


@dataclass
class Job:
    zone_id: str
    source: str
    planned_s: float
    started: float
    phase: str = "opening"  # opening | running | closing | done
    phase_ts: float = 0.0
    running_since: float | None = None
    volume_l: float = 0.0
    volume_seen: bool = False
    end_reason: str | None = None
    run_id: int | None = None


@dataclass
class Hold:
    until: float
    since: float


@dataclass
class _Cfg:
    actuators: dict[str, dict] = field(default_factory=dict)
    zones: dict[str, dict] = field(default_factory=dict)
    tanks: dict[str, dict] = field(default_factory=dict)
    g: IrrigationSettings = field(default_factory=IrrigationSettings)


def load_settings(db: Database) -> IrrigationSettings:
    with db.session() as s:
        row = s.get(AppSetting, SETTINGS_KEY)
        return IrrigationSettings.model_validate(json.loads(row.value)) if row else IrrigationSettings()


def save_settings(db: Database, g: IrrigationSettings) -> None:
    with db.session() as s:
        row = s.get(AppSetting, SETTINGS_KEY)
        payload = g.model_dump_json()
        if row is None:
            s.add(AppSetting(key=SETTINGS_KEY, value=payload, updated_at=int(time.time())))
        else:
            row.value, row.updated_at = payload, int(time.time())


class IrrigationEngine:
    def __init__(self, db: Database, outputs: OutputRegistry, ingest, gate_fn=lambda: False,
                 level_fn=lambda: "full") -> None:
        self.db, self.outputs, self.ingest = db, outputs, ingest
        self.gate_fn, self.level_fn = gate_fn, level_fn
        self._gate_memo = None
        self.clock = time.time  # tests inject a fake clock
        self.cfg = _Cfg()
        self.loaded = False
        self.estop = False
        self.on: dict[str, float] = {}
        self.jobs: dict[str, Job] = {}
        self.holds: dict[str, Hold] = {}
        self.last_end: dict[str, float] = {}
        self.fired: set[tuple] = set()
        self._last_tick: float | None = None
        self._idle_flow_since: float | None = None
        self._task = None

    def now(self) -> float:
        return self.clock()

    # ------------------------------------------------------------ config
    def reload(self) -> None:
        with self.db.session() as s:
            acts = {a.id: dict(id=a.id, name=a.name, kind=a.kind, driver=a.driver,
                               address=json.loads(a.address or "{}"), max_runtime_s=a.max_runtime_s,
                               enabled=a.enabled, feedback_sensor_id=a.feedback_sensor_id)
                    for a in s.scalars(select(Actuator).where(Actuator.kind.in_(IRRIGATION_KINDS)))}
            tanks = {t.id: dict(id=t.id, name=t.name, level_sensor_id=t.level_sensor_id,
                                float_sensor_id=t.float_sensor_id, min_level_pct=t.min_level_pct)
                     for t in s.scalars(select(Tank))}
            zones = {}
            for z in s.scalars(select(Zone)):
                d = {c.name: getattr(z, c.name) for c in Zone.__table__.columns}
                d["moisture_sensor_ids"] = json.loads(z.moisture_sensor_ids or "[]")
                d["schedule"] = json.loads(z.schedule or "[]")
                zones[z.id] = d
            row = s.get(AppSetting, ESTOP_KEY)
            self.estop = bool(row and row.value == "1")
            last = dict(s.execute(select(IrrigationRun.zone_id, func.max(IrrigationRun.end_ts))
                                  .group_by(IrrigationRun.zone_id)).all())
        self.cfg = _Cfg(acts, zones, tanks, load_settings(self.db))
        for zid, ts in last.items():
            if ts and zid not in self.last_end:
                self.last_end[zid] = float(ts)
        self.loaded = True
        self._gate_memo = None

    def _persist_estop(self, value: bool) -> None:
        with self.db.session() as s:
            row = s.get(AppSetting, ESTOP_KEY)
            if row is None:
                s.add(AppSetting(key=ESTOP_KEY, value="1" if value else "0", updated_at=int(time.time())))
            else:
                row.value, row.updated_at = "1" if value else "0", int(time.time())

    # ---------------------------------------------------------- sensors
    def _val(self, sensor_id: str | None, now: float) -> tuple[float | None, float | None]:
        if not sensor_id:
            return None, None
        lv = self.ingest.latest.get(sensor_id)
        return (lv.value, now - lv.ts) if lv else (None, None)

    def tank_status(self, tank_id: str | None, now: float) -> tuple[bool, str]:
        t = self.cfg.tanks.get(tank_id or "")
        if t is None:
            return False, "no water source (tank) assigned"
        lv, la = self._val(t["level_sensor_id"], now)
        fv, fa = self._val(t["float_sensor_id"], now)
        r = rules.TankReading(lv, la, fv, fa, bool(t["level_sensor_id"]), bool(t["float_sensor_id"]))
        return rules.tank_ok(r, t["min_level_pct"], self.cfg.g.sensor_max_age_s)

    # ------------------------------------------------------- start/stop
    def _zone_actuators_ok(self, z: dict) -> str | None:
        v = self.cfg.actuators.get(z["valve_id"])
        if v is None or not v["enabled"]:
            return "valve is missing or disabled"
        if z["pump_id"]:
            p = self.cfg.actuators.get(z["pump_id"])
            if p is None or not p["enabled"]:
                return "pump is missing or disabled"
        return None

    async def start_zone(self, zone_id: str, duration_s: float | None, source: str, now: float) -> tuple[bool, str]:
        if not self.loaded:
            self.reload()
        z = self.cfg.zones.get(zone_id)
        if z is None:
            return False, "unknown zone"
        if not z["enabled"]:
            return False, "zone is disabled"
        if self.estop:
            return False, "emergency stop is latched"
        if zone_id in self.jobs:
            return False, "zone is already running"
        bad = self._zone_actuators_ok(z)
        if bad:
            return False, bad
        if z["pump_id"]:
            ok, why = self.tank_status(z["tank_id"], now)
            if not ok:
                return False, why
        if sum(1 for j in self.jobs.values() if j.phase != "done") >= self.cfg.g.max_simultaneous_zones:
            return False, "maximum number of simultaneous zones reached"
        if source != "manual":
            last = self.last_end.get(zone_id)
            if last is not None and now - last < z["min_interval_s"]:
                return False, "minimum interval since the last run has not elapsed"
        planned = min(float(duration_s or z["default_duration_s"]), float(z["max_duration_s"]))
        for aid in filter(None, (z["valve_id"], z["pump_id"])):
            planned = min(planned, float(self.cfg.actuators[aid]["max_runtime_s"]))
        if planned <= 0:
            return False, "duration must be positive"
        job = Job(zone_id, source, planned, now, phase_ts=now)
        with self.db.session() as s:
            run = IrrigationRun(zone_id=zone_id, source=source, start_ts=int(now), planned_s=int(planned))
            s.add(run)
            s.flush()
            job.run_id = run.id
        self.jobs[zone_id] = job
        events.log_event(self.db, "info", "irrigation", f"Zone '{zone_id}' run started ({source}, {planned:.0f}s)")
        await self._reconcile(now)
        return True, f"started for up to {planned:.0f}s"

    def stop_zone(self, zone_id: str, now: float) -> bool:
        job = self.jobs.get(zone_id)
        if job is None or job.phase in ("closing", "done"):
            return False
        self._finish(job, "stopped_by_user", now)
        return True

    def _finish(self, job: Job, reason: str, now: float) -> None:
        job.end_reason = job.end_reason or reason
        z = self.cfg.zones.get(job.zone_id, {})
        job.phase, job.phase_ts = ("closing" if z.get("pump_id") else "done"), now

    def _abort(self, job: Job, reason: str, now: float, alert: bool = True) -> None:
        if job.phase == "done":
            return
        job.end_reason = job.end_reason or reason
        job.phase, job.phase_ts = "done", now  # everything off at once
        events.log_event(self.db, "warning", "irrigation", f"Zone '{job.zone_id}' aborted: {reason}")
        if alert:
            events.raise_alert(self.db, "critical", "irrigation_fault", job.zone_id,
                               f"Irrigation of '{job.zone_id}' stopped: {reason}")

    def _abort_all(self, reason: str, now: float, alert: bool = False) -> None:
        for j in self.jobs.values():
            self._abort(j, reason, now, alert)
        self.holds.clear()

    # ---------------------------------------------------- manual outputs
    async def hold(self, act_id: str, on: bool, duration_s: float | None, now: float) -> tuple[bool, str]:
        if not self.loaded:
            self.reload()
        a = self.cfg.actuators.get(act_id)
        if a is None or not a["enabled"]:
            return False, "unknown or disabled output"
        if not on:
            self.holds.pop(act_id, None)
            for j in list(self.jobs.values()):
                z = self.cfg.zones[j.zone_id]
                if act_id in (z["valve_id"], z["pump_id"]):
                    self._abort(j, "output switched off manually", now, alert=False)
            await self._reconcile(now)
            return True, "off"
        dur = min(float(duration_s or a["max_runtime_s"]), float(a["max_runtime_s"]))
        why = self._refusals(a, now, manual_check=True)
        if why:
            return False, "; ".join(why)
        self.holds[act_id] = Hold(until=now + dur, since=now)
        await self._reconcile(now)
        return (act_id in self.on), (f"on for up to {dur:.0f}s" if act_id in self.on else "could not switch on")

    # ------------------------------------------------------- emergency
    async def set_estop(self, now: float) -> None:
        self.estop = True
        self._persist_estop(True)
        self._abort_all("emergency_stop", now)
        events.log_event(self.db, "error", "safety", "EMERGENCY STOP latched")
        events.raise_alert(self.db, "critical", "emergency_stop", "", "Emergency stop is latched: all outputs off")
        await self._reconcile(now)
        self._finalize(now)

    def reset_estop(self) -> None:
        self.estop = False
        self._persist_estop(False)
        events.clear_alert(self.db, "emergency_stop", "")
        events.log_event(self.db, "warning", "safety", "Emergency stop reset by user")

    # ------------------------------------------------------ interlocks
    def _pump_zones(self, pump_id: str) -> list[dict]:
        return [z for z in self.cfg.zones.values() if z["pump_id"] == pump_id]

    def _refusals(self, a: dict, now: float, manual_check: bool = False) -> list[str]:
        tank_res, ready, needs = None, True, False
        if a["kind"] == "pump":
            zs = self._pump_zones(a["id"])
            needs = True
            if not zs:
                return ["pump is not assigned to any zone"]
            checks = [self.tank_status(z["tank_id"], now) for z in zs]
            bad = next((c for c in checks if not c[0]), None)
            tank_res = bad or (True, "ok")
            settle = self.cfg.g.valve_settle_s
            ready = any(z["valve_id"] in self.on and now - self.on[z["valve_id"]] >= settle for z in zs)
        return rules.start_refusals(kind=a["kind"], estop=self.estop, tank_ok_result=tank_res,
                                    needs_tank=needs, valve_ready_for_pump=ready)

    def _violation(self, job: Job, z: dict, now: float) -> str | None:
        g = self.cfg.g
        bad = self._zone_actuators_ok(z)
        if bad:
            return bad
        if z["pump_id"] or z["tank_id"]:
            ok, why = self.tank_status(z["tank_id"], now)
            if not ok:
                return why
        if z["flow_sensor_id"] and job.running_since is not None:
            fv, fa = self._val(z["flow_sensor_id"], now)
            why = rules.flow_violation(pump_running_s=now - job.running_since, grace_s=z["flow_grace_s"],
                                       flow_lpm=fv, flow_age_s=fa, min_lpm=z["min_flow_lpm"],
                                       max_lpm=z["max_flow_lpm"], max_age_s=g.sensor_max_age_s)
            if why:
                return why
        for aid in filter(None, (z["valve_id"], z["pump_id"])):
            fb = self.cfg.actuators[aid]["feedback_sensor_id"]
            if fb and aid in self.on:
                v, age = self._val(fb, now)
                why = rules.feedback_violation(on_for_s=now - self.on[aid], grace_s=g.valve_settle_s + 3,
                                               feedback=v, age_s=age, max_age_s=g.sensor_max_age_s)
                if why:
                    return f"{aid}: {why}"
        return None

    # -------------------------------------------------------- the tick
    async def tick(self, now: float | None = None) -> None:
        now = self.now() if now is None else now
        if not self.loaded:
            self.reload()
        dt = 0.0 if self._last_tick is None else max(0.0, now - self._last_tick)
        self._last_tick = now

        if self.estop:
            self._abort_all("emergency_stop", now)
        for aid, since in list(self.on.items()):  # hard runtime ceiling
            a = self.cfg.actuators.get(aid)
            if a is None or rules.runtime_exceeded(since, now, a["max_runtime_s"]):
                self._runtime_cut(aid, now)
        for job in list(self.jobs.values()):
            self._supervise(job, now, dt)
        for aid, h in list(self.holds.items()):
            a = self.cfg.actuators.get(aid)
            if now >= h.until or a is None or not a["enabled"]:
                self.holds.pop(aid, None)
            elif aid in self.on and (why := self._refusals(a, now)):
                self.holds.pop(aid, None)
                events.log_event(self.db, "warning", "irrigation", f"Manual hold on '{aid}' released: {'; '.join(why)}")
                events.raise_alert(self.db, "critical", "irrigation_fault", aid, f"Output '{aid}' stopped: {'; '.join(why)}")
        await self._auto(now)
        await self._reconcile(now)
        self._finalize(now)
        self._leak_watch(now)

    def _runtime_cut(self, aid: str, now: float) -> None:
        a = self.cfg.actuators.get(aid)
        self.holds.pop(aid, None)
        for j in self.jobs.values():
            z = self.cfg.zones.get(j.zone_id)
            if z is None or aid in (z["valve_id"], z["pump_id"]):
                self._abort(j, f"maximum runtime of '{aid}' reached", now, alert=False)
        events.log_event(self.db, "warning", "irrigation", f"'{aid}' forced off: maximum runtime reached")
        events.raise_alert(self.db, "warning", "max_runtime", aid,
                           f"Output '{aid}' was forced off at its maximum runtime"
                           + (f" ({a['max_runtime_s']}s)" if a else ""))
        self.on[aid] = float("inf")  # prevents re-triggering until the OFF command lands

    def _supervise(self, job: Job, now: float, dt: float) -> None:
        z = self.cfg.zones.get(job.zone_id)
        if z is None:
            self._abort(job, "zone no longer exists", now)
            return
        settle = self.cfg.g.valve_settle_s
        if job.phase == "opening":
            v_on = self.on.get(z["valve_id"])
            if v_on is not None and now - v_on >= settle:
                job.phase, job.phase_ts, job.running_since = "running", now, now
            elif now - job.phase_ts > 30 + settle:
                self._abort(job, "valve did not switch on", now)
        elif job.phase == "running":
            why = self._violation(job, z, now)
            if why:
                self._abort(job, why, now)
                return
            fv, fa = self._val(z["flow_sensor_id"], now)
            if fv is not None and fa is not None and fa <= self.cfg.g.sensor_max_age_s:
                job.volume_l += fv * dt / 60.0
                job.volume_seen = True
            if now - (job.running_since or now) >= job.planned_s:
                self._finish(job, "completed", now)
            elif z["moisture_stop_at"] is not None and job.source == "moisture" and now - (job.running_since or now) >= 10:
                m = self._moisture(z, now)
                if m is not None and m >= z["moisture_stop_at"]:
                    self._finish(job, "moisture_reached", now)
        elif job.phase == "closing" and now - job.phase_ts >= settle:
            job.phase = "done"

    def _desired(self, now: float) -> set[str]:
        if self.estop:
            return set()
        want: set[str] = set()
        for j in self.jobs.values():
            z = self.cfg.zones.get(j.zone_id)
            if z is None or j.phase == "done":
                continue
            want.add(z["valve_id"])
            if j.phase == "running" and z["pump_id"]:
                want.add(z["pump_id"])
        want.update(h for h, hold in self.holds.items() if hold.until > now)
        return want

    async def _command(self, aid: str, on: bool, now: float) -> bool:
        a = self.cfg.actuators.get(aid)
        if a is None:
            self.on.pop(aid, None)
            return True
        try:
            drv = self.outputs.get(a["driver"])
            await drv.set(OutputSpec(aid, a["kind"], a["address"]), on)
        except Exception as exc:  # noqa: BLE001 - any driver failure
            if on:
                for j in self.jobs.values():
                    z = self.cfg.zones.get(j.zone_id)
                    if z and aid in (z["valve_id"], z["pump_id"]):
                        self._abort(j, f"cannot switch '{aid}' on: {exc}", now)
                self.holds.pop(aid, None)
                events.raise_alert(self.db, "critical", "output_error", aid, f"Cannot switch '{aid}' on: {exc}")
            else:
                events.raise_alert(self.db, "critical", "output_stuck", aid,
                                   f"Cannot switch '{aid}' OFF ({exc}). Cut power manually. Retrying.")
            return False
        if on:
            self.on[aid] = now
            events.log_event(self.db, "info", "irrigation", f"'{aid}' ON")
        else:
            self.on.pop(aid, None)
            events.clear_alert(self.db, "output_stuck", aid)
            events.log_event(self.db, "info", "irrigation", f"'{aid}' OFF")
        return True

    async def _reconcile(self, now: float) -> None:
        want = self._desired(now)
        for aid in list(self.on):  # OFF first
            if aid not in want:
                await self._command(aid, False, now)
        for aid in sorted(want, key=lambda i: self.cfg.actuators.get(i, {}).get("kind") == "pump"):  # valves before pumps
            if aid in self.on or aid not in self.cfg.actuators:
                continue
            a = self.cfg.actuators[aid]
            why = self._refusals(a, now)
            if why:
                for j in self.jobs.values():
                    z = self.cfg.zones.get(j.zone_id)
                    if z and aid in (z["valve_id"], z["pump_id"]) and j.phase != "done":
                        self._abort(j, "; ".join(why), now)
                self.holds.pop(aid, None)
                continue
            await self._command(aid, True, now)

    def _finalize(self, now: float) -> None:
        for zid, job in list(self.jobs.items()):
            z = self.cfg.zones.get(zid, {})
            if job.phase != "done":
                continue
            if z and (z["valve_id"] in self.on or (z["pump_id"] and z["pump_id"] in self.on)) and not self.estop:
                if now - job.phase_ts < 30:
                    continue  # waiting for the OFF command to succeed
            actual = (now - job.running_since) if job.running_since else 0.0
            est = z.get("expected_flow_lpm") if z else None
            with self.db.session() as s:
                run = s.get(IrrigationRun, job.run_id) if job.run_id else None
                if run:
                    run.end_ts, run.actual_s = int(now), int(actual)
                    run.end_reason = job.end_reason
                    run.volume_l = round(job.volume_l, 2) if job.volume_seen else None
                    run.volume_estimate_l = round(est * actual / 60, 2) if est else None
            self.last_end[zid] = now
            events.log_event(self.db, "info", "irrigation", f"Zone '{zid}' run ended: {job.end_reason}")
            del self.jobs[zid]

    # ------------------------------------------------------- automation
    def _moisture(self, z: dict, now: float) -> float | None:
        vals = []
        for sid in z["moisture_sensor_ids"]:
            v, age = self._val(sid, now)
            if v is None or age is None or age > self.cfg.g.sensor_max_age_s:
                return None  # any stale sensor: do not decide
            vals.append(v)
        return sum(vals) / len(vals) if vals else None

    def _gate(self) -> bool:
        """The gate costs several queries: re-evaluate at most every 2 s (cleared on config changes and checklist actions)."""
        now = self.now()
        if self._gate_memo is None or now - self._gate_memo[0] >= 2.0 or now < self._gate_memo[0]:
            self._gate_memo = (now, bool(self.gate_fn()))
        return self._gate_memo[1]

    def invalidate_gate(self) -> None:
        self._gate_memo = None

    def auto_allowed(self) -> tuple[bool, str]:
        if self.estop:
            return False, "emergency stop latched"
        if not self.cfg.g.auto_enabled:
            return False, "automatic irrigation is switched off"
        if self.level_fn() == "monitor_only":
            return False, "greenhouse automation level is 'monitor only'"
        if not self._gate():
            return False, "commissioning checks have not all passed"
        return True, "ok"

    async def _auto(self, now: float) -> None:
        if not self.auto_allowed()[0]:
            return
        lt = time.localtime(now)
        today, hhmm = (lt.tm_year, lt.tm_yday), lt.tm_hour * 60 + lt.tm_min
        for z in self.cfg.zones.values():
            if not (z["enabled"] and z["auto_enabled"]) or z["id"] in self.jobs:
                continue
            for e in z["schedule"]:
                h, m = map(int, e["time"].split(":"))
                key = (z["id"], today, e["time"])
                if lt.tm_wday in e["days"] and 0 <= hhmm * 60 + lt.tm_sec - (h * 60 + m) * 60 <= 120 and key not in self.fired:
                    self.fired.add(key)
                    ok, msg = await self.start_zone(z["id"], e.get("duration_s"), "schedule", now)
                    if not ok:
                        events.log_event(self.db, "warning", "irrigation", f"Scheduled run of '{z['id']}' refused: {msg}")
            if z["id"] not in self.jobs and z["moisture_start_below"] is not None:
                mv = self._moisture(z, now)
                if mv is not None and mv < z["moisture_start_below"]:
                    ok, msg = await self.start_zone(z["id"], None, "moisture", now)
                    if not ok and "interval" not in msg:
                        key = (z["id"], "m", int(now // 600))
                        if key not in self.fired:
                            self.fired.add(key)
                            events.log_event(self.db, "info", "irrigation", f"Moisture trigger for '{z['id']}' refused: {msg}")

    def _leak_watch(self, now: float) -> None:
        g = self.cfg.g
        if g.leak_sensor_id is None or g.leak_threshold_lpm is None:
            return
        fv, fa = self._val(g.leak_sensor_id, now)
        idle = not self.on and not self.jobs
        fresh = fv is not None and fa is not None and fa <= g.sensor_max_age_s
        if idle and fresh and fv > g.leak_threshold_lpm:
            self._idle_flow_since = self._idle_flow_since or now
        else:
            self._idle_flow_since = None
        if rules.leak_suspected(outputs_idle=idle, flow_lpm=fv if fresh else None, threshold_lpm=g.leak_threshold_lpm,
                                idle_flow_s=(now - self._idle_flow_since) if self._idle_flow_since else 0,
                                confirm_s=g.leak_confirm_s):
            events.raise_alert(self.db, "critical", "leak_suspected", g.leak_sensor_id,
                               f"Water is flowing ({fv:.2f} L/min) while all outputs are off: possible leak")

    # ----------------------------------------------------------- status
    def status(self, now: float | None = None) -> dict:
        now = self.now() if now is None else now
        if not self.loaded:
            self.reload()
        zones = []
        for z in self.cfg.zones.values():
            j = self.jobs.get(z["id"])
            ok, why = self.tank_status(z["tank_id"], now) if (z["pump_id"] or z["tank_id"]) else (True, "no tank interlock")
            zones.append({"id": z["id"], "name": z["name"], "kind": z["kind"], "enabled": z["enabled"],
                          "auto_enabled": z["auto_enabled"], "tank_ok": ok, "tank_detail": why,
                          "running": None if j is None else {
                              "phase": j.phase, "source": j.source, "planned_s": j.planned_s,
                              "elapsed_s": round(now - (j.running_since or now), 1),
                              "volume_l": round(j.volume_l, 2) if j.volume_seen else None},
                          "last_end": self.last_end.get(z["id"])})
        auto_ok, auto_why = self.auto_allowed()
        return {"estop": self.estop, "auto_enabled": self.cfg.g.auto_enabled, "auto_allowed": auto_ok,
                "auto_detail": auto_why, "gate_open": self._gate(),
                "outputs": {aid: {"on": aid in self.on and self.on[aid] != float("inf"),
                                  "on_for_s": round(now - self.on[aid], 1) if aid in self.on and self.on[aid] != float("inf") else None,
                                  "kind": a["kind"], "name": a["name"], "max_runtime_s": a["max_runtime_s"]}
                            for aid, a in self.cfg.actuators.items()},
                "zones": zones}

    # ------------------------------------------------------ lifecycle
    async def startup(self, now: float | None = None) -> None:
        self.reload()
        now = self.now() if now is None else now
        for aid in self.cfg.actuators:
            await self._command(aid, False, now)  # known safe state
        if self.estop:
            events.log_event(self.db, "error", "safety", "Started with emergency stop still latched")

    async def shutdown(self) -> None:
        now = self.now()
        self._abort_all("shutdown", now)
        for aid in list(self.on):
            await self._command(aid, False, now)

    def start(self) -> None:
        import asyncio

        async def loop():
            while True:
                try:
                    await self.tick()
                except Exception:  # noqa: BLE001
                    log.exception("irrigation tick failed")
                    try:
                        for aid in list(self.on):
                            await self._command(aid, False, time.time())
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
