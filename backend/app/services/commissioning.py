"""Commissioning checklist and the safety gate for automatic operation.

A check passes when its automatic test passed (where one exists) AND, for
checks about the physical world, a person has attested they performed the
physical test. Passes are bound to a hash of the safety-relevant equipment
configuration: changing actuators, tanks or zone wiring invalidates them.

Automatic tests exercise the interlock LOGIC and read live data; they cannot
see your wiring. That is why physical checks need human attestation.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass

from sqlalchemy import select

from app.automation import rules
from app.core.db import Database
from app.core.models import Actuator, AppSetting, CommissioningRecord, Sensor, Tank, Zone


@dataclass(frozen=True)
class Check:
    id: str
    title: str
    has_auto: bool
    manual_required: bool
    instructions: str
    applies: str = "always"  # always | outputs | pumps | heaters | windows


CHECKS: list[Check] = [
    Check("sensor_communication", "Sensor communication", True, False,
          "Every enabled sensor must have a fresh reading. Interlock sensors must not be simulated while real outputs exist."),
    Check("modbus_communication", "Modbus communication", True, False,
          "Each configured RS485 bus must have at least one sensor answering."),
    Check("gpio_operation", "GPIO operation", False, True,
          "Switch each GPIO output with the Control page and confirm with a meter or by observing the device. "
          "Confirm outputs are OFF after a reboot.", "outputs"),
    Check("mqtt_communication", "MQTT communication", False, True,
          "No MQTT/ESP32 nodes are supported yet. Attest only if you use none."),
    Check("heater_protection", "Heater / CO2 hardware protection", False, True,
          "Confirm every heater has an independent hardware over-temperature cut-out and every CO2 supply an independent "
          "shut-off (and a room CO2 alarm), that work with the Raspberry Pi switched off. Test them.", "heaters"),
    Check("window_limits", "Window limit switches", False, True,
          "Confirm each motorised window/screen has end-of-travel limit switches (or motor protection) that stop the "
          "motor independently, and that open and close are never energised together.", "windows"),
    Check("actuator_feedback", "Actuator feedback", False, True,
          "For each pump and valve: command ON and confirm physically that it moves/runs; command OFF and confirm it stops. "
          "Check feedback sensors where fitted.", "outputs"),
    Check("pump_protection", "Pump protection", True, True,
          "Software test checks dead-head and runtime limits. Physically confirm a hardware float switch (or equivalent) "
          "cuts pump power when the tank is empty, with the Raspberry Pi switched off.", "pumps"),
    Check("water_level_interlock", "Water-level interlock", True, True,
          "Software test checks the low-level logic. Physically lower the water level (or lift the float) and confirm the "
          "pump refuses to start / stops.", "pumps"),
    Check("emergency_stop", "Emergency stop", True, True,
          "Software test checks the latch. Physically press the hardware e-stop and confirm all pumps and valves lose "
          "power, independent of the software.", "outputs"),
    Check("watchdog", "Hardware watchdog", False, True,
          "Confirm a hardware watchdog is configured and that a hung system reboots (there is no automated watchdog test yet)."),
    Check("automatic_restart", "Automatic restart", False, True,
          "Cut power to the Pi and restore it: the service must restart on its own and every output must stay OFF.", "outputs"),
    Check("database_operation", "Database operation", True, False, "Write, read and delete a record."),
    Check("backup_restore", "Backup and restore", True, False,
          "Automatic test: writes a backup, verifies its checksum and integrity, opens a copy as a database and reads it back. "
          "You must still copy backups OFF the Raspberry Pi (BACKUP_RESTORE.md)."),
]
BY_ID = {c.id: c for c in CHECKS}


def _applicable(db: Database) -> dict[str, bool]:
    from app.core.models import Window
    with db.session() as s:
        kinds = [k for (k,) in s.execute(select(Actuator.kind).where(Actuator.enabled.is_(True)))]
        n_win = len(list(s.scalars(select(Window.id))))
    return {"always": True, "outputs": bool(kinds), "pumps": "pump" in kinds,
            "heaters": any(k in ("heater", "co2") for k in kinds), "windows": n_win > 0}


def config_hash(db: Database) -> str:
    from app.core.models import Window
    with db.session() as s:
        acts = [[a.id, a.kind, a.driver, a.address, a.max_runtime_s, a.enabled, a.feedback_sensor_id, a.interlocks]
                for a in s.scalars(select(Actuator).order_by(Actuator.id))]
        wins = [[w.id, w.open_output_id, w.close_output_id, w.travel_time_s, w.rain_sensor_id, w.wind_sensor_id,
                 w.wind_max_ms, w.enabled] for w in s.scalars(select(Window).order_by(Window.id))]
        tanks = [[t.id, t.level_sensor_id, t.float_sensor_id, t.min_level_pct]
                 for t in s.scalars(select(Tank).order_by(Tank.id))]
        zones = [[z.id, z.valve_id, z.pump_id, z.tank_id, z.flow_sensor_id, z.max_duration_s, z.min_flow_lpm,
                  z.max_flow_lpm, z.enabled] for z in s.scalars(select(Zone).order_by(Zone.id))]
    return hashlib.sha256(json.dumps([acts, tanks, zones, wins], sort_keys=True).encode()).hexdigest()[:16]


# --------------------------------------------------------------- auto tests

def _t_sensor_comm(ctx) -> tuple[bool, str]:
    with ctx.db.session() as s:
        sensors = list(s.scalars(select(Sensor).where(Sensor.enabled.is_(True))))
        acts = list(s.scalars(select(Actuator).where(Actuator.enabled.is_(True))))
        tanks = list(s.scalars(select(Tank)))
        zones = list(s.scalars(select(Zone)))
    if not sensors:
        return False, "no sensors configured"
    now = time.time()
    stale = [x.id for x in sensors if x.id not in ctx.ingest.latest
             or now - ctx.ingest.latest[x.id].ts > max(3 * ctx.settings.poll_interval_s, 15)]
    if stale:
        return False, f"no fresh reading from: {', '.join(stale)}"
    real_outputs = any(a.driver != "simulated_output" for a in acts)
    sim = {x.id for x in sensors if x.simulated}
    interlock = {i for t in tanks for i in (t.level_sensor_id, t.float_sensor_id) if i}
    interlock |= {z.flow_sensor_id for z in zones if z.flow_sensor_id}
    bad = sorted(interlock & sim)
    if real_outputs and bad:
        return False, f"interlock sensors are simulated while real outputs are configured: {', '.join(bad)}"
    return True, f"{len(sensors)} sensors fresh"


def _t_modbus(ctx) -> tuple[bool, str]:
    buses = ctx.ctx.buses.configs()
    if not buses:
        return True, "no RS485 bus configured (not applicable)"
    with ctx.db.session() as s:
        import json as _j
        rows = list(s.scalars(select(Sensor).where(Sensor.driver == "modbus_rtu", Sensor.enabled.is_(True))))
        by_bus: dict[str, list[str]] = {}
        for r in rows:
            by_bus.setdefault(_j.loads(r.address).get("bus", "?"), []).append(r.id)
    now = time.time()
    for b in buses:
        ok = any(i in ctx.ingest.latest and now - ctx.ingest.latest[i].ts <= max(3 * ctx.settings.poll_interval_s, 15)
                 for i in by_bus.get(b.id, []))
        if not ok:
            return False, f"no sensor on bus '{b.id}' is answering"
    return True, f"{len(buses)} bus(es) answering"


def _t_database(ctx) -> tuple[bool, str]:
    key = "selftest_probe"
    try:
        with ctx.db.session() as s:
            s.merge(AppSetting(key=key, value="ok", updated_at=int(time.time())))
        with ctx.db.session() as s:
            row = s.get(AppSetting, key)
            good = row is not None and row.value == "ok"
            if row:
                s.delete(row)
        return good, "write/read/delete ok" if good else "read-back mismatch"
    except Exception as exc:  # noqa: BLE001
        return False, f"database error: {exc}"


def _t_pump_protection(ctx) -> tuple[bool, str]:
    with ctx.db.session() as s:
        pumps = list(s.scalars(select(Actuator).where(Actuator.kind == "pump")))
        zones = list(s.scalars(select(Zone)))
    if not pumps:
        return True, "no pumps configured"
    if rules.start_refusals(kind="pump", estop=False, tank_ok_result=(True, "ok"), needs_tank=True,
                            valve_ready_for_pump=False) == []:
        return False, "logic error: dead-head not refused"
    if not rules.runtime_exceeded(0, 101, 100) or rules.runtime_exceeded(0, 99, 100):
        return False, "logic error: runtime limit"
    for p in pumps:
        zs = [z for z in zones if z.pump_id == p.id]
        if not zs:
            return False, f"pump '{p.id}' is not assigned to a zone (it could never be protected)"
        if any(not z.tank_id for z in zs):
            return False, f"a zone of pump '{p.id}' has no tank interlock"
        if p.max_runtime_s <= 0:
            return False, f"pump '{p.id}' has no maximum runtime"
    return True, "dead-head, runtime and tank-assignment rules pass"


def _t_water_level(ctx) -> tuple[bool, str]:
    r = rules.TankReading
    cases = [
        (r(10, 1, None, None, True, False), 15, False),
        (r(50, 1, None, None, True, False), 15, True),
        (r(50, 99, None, None, True, False), 15, False),   # stale
        (r(None, None, 0.0, 1, False, True), 15, False),   # float says low
        (r(None, None, 1.0, 1, False, True), 15, True),
        (r(None, None, None, None, False, False), 15, False),  # no sensors
    ]
    for t, mn, expected in cases:
        if rules.tank_ok(t, mn, 20)[0] != expected:
            return False, "logic error in tank interlock"
    with ctx.db.session() as s:
        tanks = list(s.scalars(select(Tank)))
        pumps = list(s.scalars(select(Actuator).where(Actuator.kind == "pump")))
    if pumps and not tanks:
        return False, "pumps exist but no tank is configured"
    for t in tanks:
        if not t.level_sensor_id and not t.float_sensor_id:
            return False, f"tank '{t.id}' has no level or float sensor"
    return True, "interlock logic passes; all tanks have sensors"


def _t_estop(ctx) -> tuple[bool, str]:
    for kind in ("pump", "valve", "dosing", "other"):
        if not rules.start_refusals(kind=kind, estop=True, tank_ok_result=(True, "ok"), needs_tank=True,
                                    valve_ready_for_pump=True):
            return False, f"e-stop does not block '{kind}' outputs"
    return True, "latched e-stop refuses all output types"


def _t_backup(ctx) -> tuple[bool, str]:
    from app.services import backup
    r = backup.verify_roundtrip(ctx.db, ctx.settings)
    return r["ok"], r["detail"]


AUTO = {"backup_restore": _t_backup, "sensor_communication": _t_sensor_comm, "modbus_communication": _t_modbus,
        "database_operation": _t_database, "pump_protection": _t_pump_protection,
        "water_level_interlock": _t_water_level, "emergency_stop": _t_estop}


@dataclass
class Ctx:
    db: Database
    ingest: object
    settings: object
    ctx: object  # HalContext


# ------------------------------------------------------------------ status

def _records(db: Database) -> dict[str, CommissioningRecord]:
    with db.session() as s:
        return {r.check_id: r for r in s.scalars(select(CommissioningRecord))}


def status(db: Database, engine=None) -> dict:
    h = config_hash(db)
    recs = _records(db)
    applic = _applicable(db)
    with db.session() as s:
        n_act = len(list(s.scalars(select(Actuator.id).where(Actuator.enabled.is_(True)))))
    out, all_ok = [], True
    for c in CHECKS:
        r = recs.get(c.id)
        auto_valid = bool(r and r.auto_ok and r.auto_hash == h)
        manual_valid = bool(r and r.manual_ok and r.manual_hash == h)
        stale = bool(r and ((r.auto_ts and r.auto_hash != h) or (r.manual_ok and r.manual_hash != h)))
        applicable = applic.get(c.applies, True)
        passed = (not applicable) or ((auto_valid or not c.has_auto) and (manual_valid or not c.manual_required))
        all_ok &= passed
        out.append({"id": c.id, "title": c.title, "instructions": c.instructions, "has_auto": c.has_auto,
                    "applicable": applicable,
                    "manual_required": c.manual_required, "passed": passed,
                    "auto": None if not c.has_auto else {
                        "ok": auto_valid, "last_ok": r.auto_ok if r else None, "detail": r.auto_detail if r else "not run",
                        "ts": r.auto_ts if r else None},
                    "manual": None if not c.manual_required else {
                        "attested": manual_valid, "note": r.manual_note if r else "", "ts": r.manual_ts if r else None},
                    "invalidated_by_config_change": stale})
    allowed = all_ok and n_act > 0
    reason = ("all checks passed" if allowed else
              "no actuators configured" if n_act == 0 and all_ok else
              f"{sum(not c['passed'] for c in out)} of {len(out)} checks not passed")
    return {"production_automation_allowed": allowed, "reason": reason, "config_hash": h, "checks": out,
            "estop": bool(engine.estop) if engine else False,
            "note": ("Hardware safety protections (thermal cut-outs, float switches, e-stop, breakers/RCD) must "
                     "be independent of this software.")}


def gate_open(db: Database) -> bool:
    return bool(status(db)["production_automation_allowed"])


def run_auto(check_id: str, ctx: Ctx) -> dict:
    fn = AUTO.get(check_id)
    if fn is None:
        raise KeyError(check_id)
    ok, detail = fn(ctx)
    with ctx.db.session() as s:
        r = s.get(CommissioningRecord, check_id) or CommissioningRecord(check_id=check_id)
        r.auto_ok, r.auto_ts, r.auto_detail, r.auto_hash = ok, int(time.time()), detail, config_hash(ctx.db)
        s.merge(r)
    return {"ok": ok, "detail": detail}


def attest(db: Database, check_id: str, note: str) -> None:
    c = BY_ID[check_id]
    if not c.manual_required:
        raise ValueError("this check does not take a manual attestation")
    if len(note.strip()) < 10:
        raise ValueError("describe what you tested (at least 10 characters)")
    with db.session() as s:
        r = s.get(CommissioningRecord, check_id) or CommissioningRecord(check_id=check_id)
        r.manual_ok, r.manual_ts, r.manual_note, r.manual_hash = True, int(time.time()), note.strip(), config_hash(db)
        s.merge(r)


def revoke(db: Database, check_id: str) -> None:
    with db.session() as s:
        r = s.get(CommissioningRecord, check_id)
        if r:
            r.manual_ok, r.auto_ok = False, False
