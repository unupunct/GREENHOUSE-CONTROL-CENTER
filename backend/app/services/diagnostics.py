"""System health, communication statistics and the live diagnosis assistant."""

from __future__ import annotations

import json
import time
from collections import defaultdict

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.models import Actuator, AppSetting, Event, MaintenanceTask, Sensor
from app.services import events, maintenance, system_info

SETTINGS_KEY = "diagnostics"


class DiagSettings(BaseModel):
    """Thresholds. Disk/CPU/memory values are starting assumptions: change them to suit your Pi."""

    disk_min_gb: float = Field(1.0, gt=0)
    cpu_temp_warn_c: float = Field(75.0, gt=0)
    cpu_temp_crit_c: float = Field(80.0, gt=0)  # Raspberry Pi starts throttling around 80 C
    memory_warn_pct: float = Field(90.0, gt=0, le=100)
    battery_min_v: float | None = Field(None, gt=0)  # battery voltage sensors (kind 'battery') below this alert


def load_settings(db) -> DiagSettings:
    with db.session() as s:
        row = s.get(AppSetting, SETTINGS_KEY)
        return DiagSettings.model_validate(json.loads(row.value)) if row else DiagSettings()


def save_settings(db, g: DiagSettings) -> None:
    with db.session() as s:
        row = s.get(AppSetting, SETTINGS_KEY)
        payload = g.model_dump_json()
        if row is None:
            s.add(AppSetting(key=SETTINGS_KEY, value=payload, updated_at=int(time.time())))
        else:
            row.value, row.updated_at = payload, int(time.time())


def _c(name, status, detail):
    return {"name": name, "status": status, "detail": detail}


def health(app, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    st, db, cfg = app.state, app.state.db, load_settings(app.state.db)
    sysinfo = system_info.collect(st.settings.data_dir)
    comps = []
    free = sysinfo["disk_free_gb"]
    comps.append(_c("Storage", "crit" if free < cfg.disk_min_gb else "ok", f"{free} GB free of {sysinfo['disk_total_gb']} GB"))
    comps.append(_c("Memory", "warn" if sysinfo["memory_percent"] > cfg.memory_warn_pct else "ok", f"{sysinfo['memory_percent']}% used"))
    t = sysinfo["cpu_temp_c"]
    comps.append(_c("CPU temperature", "ok" if t is None else "crit" if t >= cfg.cpu_temp_crit_c else "warn" if t >= cfg.cpu_temp_warn_c else "ok",
                    "not available on this computer" if t is None else f"{t:.0f} °C"))
    yr = time.localtime(now).tm_year
    comps.append(_c("Time zone", "info", time.strftime("%Z (UTC%z)", time.localtime(now)) + ": schedules, daily totals and reports use this; it must match the greenhouse's local time"))
    comps.append(_c("System clock", "crit" if yr < 2024 else "ok", f"year {yr}" + (": the clock looks wrong; reports and schedules depend on it" if yr < 2024 else "")))
    integ = db.integrity_check()
    size = st.settings.db_path.stat().st_size / 1e6 if st.settings.db_path.exists() else 0
    comps.append(_c("Database", "ok" if integ == "ok" else "crit", f"integrity {integ}, {size:.1f} MB"))
    latest = st.ingest.latest
    newest = max((lv.ts for lv in latest.values()), default=None)
    age = None if newest is None else now - newest
    comps.append(_c("Sensor polling", "crit" if age is None or age > max(10 * st.settings.poll_interval_s, 60) else "ok",
                    "no readings yet" if age is None else f"newest reading {age:.0f}s ago"))
    with db.session() as s:
        sensors = list(s.scalars(select(Sensor).where(Sensor.enabled.is_(True))))
    stale = [x.id for x in sensors if x.id not in latest or now - latest[x.id].ts > max(3 * st.settings.poll_interval_s, 15)]
    comps.append(_c("Sensors", "ok" if not stale else "warn" if len(stale) < max(1, len(sensors)) else "crit",
                    f"{len(sensors) - len(stale)}/{len(sensors)} answering" + (f"; silent: {', '.join(stale[:8])}" if stale else "")))
    bat = [x for x in sensors if x.kind == "battery"]
    if bat:
        low = [x.id for x in bat if cfg.battery_min_v is not None and x.id in latest and latest[x.id].value < cfg.battery_min_v]
        comps.append(_c("Battery", "crit" if low else "ok", ", ".join(f"{x.id} {latest[x.id].value:g} V" for x in bat if x.id in latest) or "no readings"))
    else:
        comps.append(_c("Battery", "info", "no battery sensor registered (add one with kind 'battery' to monitor a UPS)"))
    from app.services import backup as _bk
    bset, last = _bk.load_settings(db), _bk.last_backup(st.settings)
    if not bset.enabled:
        comps.append(_c("Backups", "warn", "scheduled backups are switched off"))
    elif last is None:
        comps.append(_c("Backups", "warn", "no backup yet (the first one runs at " + bset.time + " or press 'Back up now')"))
    else:
        age_h = (now - last["created_ts"]) / 3600
        comps.append(_c("Backups", "warn" if age_h > 72 else "ok", f"last backup {age_h:.0f} h ago" + ("" if bset.copy_dir else "; not copied off this computer")))
    comps.append(_c("Emergency stop", "warn" if st.engine.estop else "ok", "LATCHED: all outputs off" if st.engine.estop else "clear"))
    from app.services import commissioning
    gate = commissioning.status(db, st.engine)
    comps.append(_c("Commissioning", "ok" if gate["production_automation_allowed"] else "info", gate["reason"]))
    with db.session() as s:
        tasks = list(s.scalars(select(MaintenanceTask)))
    over = [t.title for t in tasks if maintenance.status_of(t, now)["status"] == "overdue"]
    comps.append(_c("Maintenance", "warn" if over else "ok", f"{len(over)} overdue" + (f": {over[0]}" if over else "")))
    worst = "crit" if any(c["status"] == "crit" for c in comps) else "warn" if any(c["status"] == "warn" for c in comps) else "ok"
    return {"overall": worst, "components": comps, "generated_at": int(now), "thresholds": cfg.model_dump()}


def sync_health_alerts(app, now: float | None = None) -> None:
    """Raise/clear one alert per critical health component."""
    h = health(app, now)
    for c in h["components"]:
        if c["name"] in ("Storage", "CPU temperature", "System clock", "Database", "Battery"):
            if c["status"] == "crit":
                events.raise_alert(app.state.db, "critical", "system_health", c["name"], f"{c['name']}: {c['detail']}")
            else:
                events.clear_alert(app.state.db, "system_health", c["name"])


def comms(app, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    st = app.state
    with st.db.session() as s:
        sensors = list(s.scalars(select(Sensor).where(Sensor.enabled.is_(True))))
    rows, buses = [], defaultdict(lambda: {"ok": 0, "fail": 0, "sensors": 0})
    for x in sensors:
        a = json.loads(x.address or "{}")
        s_ = st.ingest.stats.get(x.id, {"ok": 0, "fail": 0, "last_error": None, "last_ok_ts": None, "last_fail_ts": None, "last_ms": None})
        total = s_["ok"] + s_["fail"]
        rows.append({"sensor_id": x.id, "driver": x.driver, "protocol": x.protocol, "bus": a.get("bus"), "ok": s_["ok"], "fail": s_["fail"],
                     "success_pct": round(100 * s_["ok"] / total, 1) if total else None, "last_error": s_["last_error"],
                     "last_ok_age_s": None if s_["last_ok_ts"] is None else round(now - s_["last_ok_ts"]), "last_ms": s_["last_ms"],
                     "simulated": x.simulated})
        key = f"{x.protocol}:{a.get('bus', '')}" if x.driver != "simulated" else "simulated"
        buses[key]["ok"] += s_["ok"]
        buses[key]["fail"] += s_["fail"]
        buses[key]["sensors"] += 1
    return {"sensors": rows, "buses": [{"bus": k, **v, "success_pct": round(100 * v["ok"] / (v["ok"] + v["fail"]), 1) if v["ok"] + v["fail"] else None}
                                       for k, v in sorted(buses.items())],
            "note": "Counters are kept in memory since the last restart."}


def errors(db, days: float = 7, level: str | None = None, source: str | None = None, limit: int = 300) -> list[dict]:
    since = int(time.time() - days * 86400)
    with db.session() as s:
        q = select(Event).where(Event.ts >= since, Event.level.in_([level] if level else ["error", "warning"]))
        if source:
            q = q.where(Event.source == source)
        rows = s.scalars(q.order_by(Event.id.desc()).limit(min(limit, 1000))).all()
    return [{"id": e.id, "ts": e.ts, "level": e.level, "source": e.source, "message": e.message} for e in rows]


# --------------------------------------------------------- assistant

def _f(status: str, text: str) -> dict:
    return {"status": status, "text": text}


def diagnose(app, kind: str, id_: str, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    fn = {"sensor": _d_sensor, "output": _d_output, "zone": _d_zone, "window": _d_window}.get(kind)
    if fn is None:
        raise ValueError(f"cannot diagnose '{kind}'")
    findings, steps = fn(app, id_, now)
    problems = [f for f in findings if f["status"] == "problem"]
    return {"kind": kind, "id": id_, "verdict": "problem found" if problems else "no problem found", "findings": findings,
            "next_steps": steps if problems else ["Nothing obviously wrong: watch it for a while or run a test read/command."]}


def _recent_events(db, needle: str, n=5) -> list[str]:
    with db.session() as s:
        rows = s.scalars(select(Event).where(Event.message.contains(needle)).order_by(Event.id.desc()).limit(n)).all()
    return [f"{time.strftime('%H:%M:%S', time.localtime(e.ts))} {e.message}" for e in rows]


def _d_sensor(app, sid: str, now: float):
    st, f, steps = app.state, [], []
    with st.db.session() as s:
        x = s.get(Sensor, sid)
    if x is None:
        return [_f("problem", f"No sensor '{sid}' is registered.")], ["Check the ID on the Hardware page."]
    a = json.loads(x.address or "{}")
    f.append(_f("ok" if x.enabled else "problem", "Sensor is enabled." if x.enabled else "Sensor is DISABLED."))
    if not x.enabled:
        steps.append("Enable it on the Hardware page.")
    if x.simulated:
        f.append(_f("info", "This is a SIMULATED sensor: its values are generated, not measured."))
    lv = st.ingest.latest.get(sid)
    if lv is None:
        f.append(_f("problem", "No reading has been received since start-up."))
    else:
        age = now - lv.ts
        bad = age > max(3 * st.settings.poll_interval_s, 15)
        f.append(_f("problem" if bad else "ok", f"Last reading {lv.value:g} {x.unit} was {age:.0f}s ago" + (": too old." if bad else ".")))
        if x.min_valid is not None and x.max_valid is not None and not (x.min_valid <= lv.value <= x.max_valid):
            f.append(_f("problem", f"Value is outside the valid range {x.min_valid:g}-{x.max_valid:g}."))
    s_ = st.ingest.stats.get(sid)
    if s_ and s_["fail"]:
        f.append(_f("problem" if (lv is None or s_["last_fail_ts"] and s_["last_fail_ts"] >= (lv.ts if lv else 0)) else "info",
                    f"{s_['fail']} failed and {s_['ok']} successful reads since start. Last error: {s_['last_error']}"))
        steps.append("Meaning of the last error: " + _explain_short(s_["last_error"]))
    if x.driver == "modbus_rtu":
        bus = a.get("bus")
        if bus not in {b.id for b in st.ctx.buses.configs()}:
            f.append(_f("problem", f"RS485 bus '{bus}' is not configured."))
            steps.append("Add the bus (port, baud, parity) on the Hardware page.")
        else:
            f.append(_f("ok", f"RS485 bus '{bus}' is configured."))
        steps.append("Use Hardware → Scan on a small address range to see which slave addresses answer.")
    if x.driver == "ds18b20":
        listed = st.drivers.get("ds18b20").list_devices()
        f.append(_f("ok" if a.get("device_id") in listed else "problem", f"1-Wire devices visible to the system: {', '.join(listed) or 'none'}."))
        if a.get("device_id") not in listed:
            steps.append("Enable 1-Wire, check the 4.7 kΩ pull-up and the device ID.")
    if x.cal_gain not in (None, 1.0) or x.cal_offset not in (None, 0.0):
        f.append(_f("info", f"Calibration is active: calibrated = {x.cal_gain:.4f} × raw + {x.cal_offset:.4f}."))
    ev = _recent_events(st.db, sid)
    if ev:
        f.append(_f("info", "Recent events: " + " | ".join(ev)))
    if not steps:
        steps = ["Use Hardware → Test on this sensor and read the error text."]
    return f, steps


def _explain_short(text: str | None) -> str:
    from app.services.troubleshoot import explain
    e = explain(text or "")
    return f"{e['title']}: {e['plain']}"


def _d_output(app, oid: str, now: float):
    st, f, steps = app.state, [], []
    with st.db.session() as s:
        a = s.get(Actuator, oid)
    if a is None:
        return [_f("problem", f"No output '{oid}' is registered.")], ["Check the ID."]
    irrigation = a.kind in ("pump", "valve", "dosing")
    eng = st.engine if irrigation else st.climate
    f.append(_f("ok" if a.enabled else "problem", "Output is enabled." if a.enabled else "Output is DISABLED."))
    if st.engine.estop:
        f.append(_f("problem", "The emergency stop is LATCHED: nothing can switch on."))
        steps.append("Find the cause, then reset the emergency stop.")
    on = oid in eng.on and eng.on[oid] != float("inf")
    f.append(_f("info", "Currently ON." if on else "Currently OFF."))
    auto_ok, why = eng.auto_allowed()
    f.append(_f("info", "Automatic control is active." if auto_ok else f"Automatic control is not running: {why}."))
    if not irrigation:
        c = st.climate
        if oid in c.holds:
            f.append(_f("info", f"A manual override ('{c.holds[oid].state}') is in force until it expires or you press Auto."))
        if c.blocked_until.get(oid, 0) > now:
            f.append(_f("problem", f"Blocked for another {c.blocked_until[oid] - now:.0f}s after a forced stop or error."))
        if c._refusal_logged.get(oid):
            f.append(_f("problem", f"A rule wants it on but an interlock refuses: {c._refusal_logged[oid]}."))
            steps.append(_explain_short(c._refusal_logged[oid]))
    else:
        eng.reload() if not eng.loaded else None
        cfg = eng.cfg.actuators.get(oid)
        if cfg:
            why = eng._refusals(cfg, now)
            if why:
                f.append(_f("problem", "Would be refused right now: " + "; ".join(why)))
                steps += [_explain_short(w) for w in why]
        if oid in eng.holds:
            f.append(_f("info", "A manual hold is in force."))
    f.append(_f("info", f"Hard maximum runtime: {a.max_runtime_s}s. Driver: {a.driver}."))
    for line in _recent_events(st.db, f"'{oid}'"):
        f.append(_f("info", line))
    if not steps:
        steps = ["Try the manual On button and read the message; check the driver wiring (relay board power, bus, GPIO)."]
    return f, steps


def _d_zone(app, zid: str, now: float):
    st, f, steps = app.state, [], []
    eng = st.engine
    if not eng.loaded:
        eng.reload()
    z = eng.cfg.zones.get(zid)
    if z is None:
        return [_f("problem", f"No zone '{zid}'.")], ["Check the ID."]
    f.append(_f("ok" if z["enabled"] else "problem", "Zone is enabled." if z["enabled"] else "Zone is DISABLED."))
    bad = eng._zone_actuators_ok(z)
    f.append(_f("problem" if bad else "ok", bad or "Valve and pump are present and enabled."))
    if z["pump_id"] or z["tank_id"]:
        ok, why = eng.tank_status(z["tank_id"], now)
        f.append(_f("ok" if ok else "problem", "Water source is OK." if ok else f"Water source: {why}."))
        if not ok:
            steps.append(_explain_short(why))
    if eng.estop:
        f.append(_f("problem", "The emergency stop is latched."))
    if zid in eng.jobs:
        f.append(_f("info", f"Running now ({eng.jobs[zid].phase})."))
    last = eng.last_end.get(zid)
    if last:
        f.append(_f("info", f"Last run ended {now - last:.0f}s ago; minimum interval {z['min_interval_s']}s applies to automatic starts."))
    ok, why = eng.auto_allowed()
    f.append(_f("info", "Automatic irrigation is allowed." if ok else f"Automatic irrigation is not running: {why}."))
    if z["auto_enabled"] is False:
        f.append(_f("info", "This zone's own automatic switch is off."))
    for line in _recent_events(st.db, f"'{zid}'"):
        f.append(_f("info", line))
    return f, steps or ["Try 'Water now' and read the message."]


def _d_window(app, wid: str, now: float):
    st, f, steps = app.state, [], []
    c = st.climate
    if not c.loaded:
        c.reload()
    w = c.cfg.windows.get(wid)
    if w is None:
        return [_f("problem", f"No window '{wid}'.")], ["Check the ID."]
    ws = c.win[wid]
    pos = c._shown_pos(wid, now)
    f.append(_f("info", "Position unknown: the next move will home against the closed end." if pos is None else f"Estimated position {pos:g}% (from motor run time)."))
    f.append(_f("info", f"Moving: {ws.moving}." if ws.moving else "Not moving."))
    if ws.hazard:
        f.append(_f("problem", f"Closing because: {ws.hazard}."))
        steps.append(_explain_short(ws.hazard))
    for oid in (w["open_output_id"], w["close_output_id"]):
        if c.blocked_until.get(oid, 0) > now:
            f.append(_f("problem", f"Motor output '{oid}' is blocked for {c.blocked_until[oid] - now:.0f}s after a forced stop."))
    if st.engine.estop:
        f.append(_f("problem", "The emergency stop is latched."))
    ok, why = c.auto_allowed()
    f.append(_f("info", "Automatic control active." if ok else f"Automatic control not running: {why}."))
    if wid in c.win_holds:
        f.append(_f("info", "A manual position override is in force."))
    return f, steps or ["Command a position manually and watch the motor outputs; check limit switches and the motor runtime limit."]
