"""Maintenance schedule: tasks, due status, suggestions from the registered equipment, alerts."""

from __future__ import annotations

import re
import time

from sqlalchemy import select

from app.core.db import Database
from app.core.models import Actuator, MaintenanceLog, MaintenanceTask, Sensor, Tank
from app.services import events

DAY = 86400
CATEGORIES = ["calibration", "filter", "pump", "valve", "fan", "window", "safety", "battery", "storage", "backup", "other"]

# Starting suggestions only: adjust to your equipment, water and manufacturer instructions.
SENSOR_RULES = {
    "ph": ("calibration", "Calibrate pH probe", 30), "ec": ("calibration", "Calibrate EC probe", 60),
    "soil_moisture": ("calibration", "Check soil probe contact and calibration", 90),
    "co2": ("calibration", "Check CO2 sensor against fresh outdoor air", 180),
    "par": ("calibration", "Compare PAR sensor with a reference and clean the diffuser", 365),
    "humidity": ("calibration", "Check humidity sensor drift", 365), "temperature": ("calibration", "Compare temperature sensor with a reference", 365),
}
ACTUATOR_RULES = {
    "pump": ("pump", "Inspect pump (noise, leaks, seals, suction filter)", 90), "valve": ("valve", "Inspect valve (leaks, diaphragm, coil)", 180),
    "fan": ("fan", "Clean and inspect fan (blades, bearings, louvres)", 90), "motor": ("window", "Check window actuator, hinges and limit switches", 90),
    "heater": ("safety", "Test heater over-temperature cut-out", 90), "co2": ("safety", "Test CO2 shut-off and room CO2 alarm", 90),
}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40]


def _task_id(title: str, subject: str) -> str:
    return slug(f"{subject}_{title}" if subject else title)


def status_of(t: MaintenanceTask, now: float) -> dict:
    base = t.last_done_ts if t.last_done_ts is not None else t.created_at
    due = base + t.interval_days * DAY
    left = due - now
    if not t.enabled:
        st = "disabled"
    elif left < 0:
        st = "overdue"
    elif left <= min(7 * DAY, 0.2 * t.interval_days * DAY):
        st = "due_soon"
    else:
        st = "ok"
    return {"status": st, "next_due_ts": int(due), "days_left": round(left / DAY, 1)}


def task_dict(t: MaintenanceTask, now: float) -> dict:
    return {"id": t.id, "title": t.title, "category": t.category, "subject_kind": t.subject_kind, "subject_id": t.subject_id,
            "interval_days": t.interval_days, "last_done_ts": t.last_done_ts, "enabled": t.enabled, "notes": t.notes,
            **status_of(t, now)}


def suggestions(db: Database) -> list[dict]:
    """Tasks that fit the REAL (non-simulated) equipment currently registered."""
    out: list[dict] = []
    with db.session() as s:
        sensors = list(s.scalars(select(Sensor).where(Sensor.simulated.is_(False), Sensor.enabled.is_(True))))
        acts = list(s.scalars(select(Actuator).where(Actuator.driver != "simulated_output", Actuator.enabled.is_(True))))
        tanks = list(s.scalars(select(Tank)))
    for x in sensors:
        r = SENSOR_RULES.get(x.kind)
        if r:
            out.append({"category": r[0], "title": f"{r[1]}: {x.name}", "subject_kind": "sensor", "subject_id": x.id, "interval_days": r[2]})
    for a in acts:
        r = ACTUATOR_RULES.get(a.kind)
        if r:
            out.append({"category": r[0], "title": f"{r[1]}: {a.name}", "subject_kind": "actuator", "subject_id": a.id, "interval_days": r[2]})
    pumps = [a for a in acts if a.kind == "pump"]
    if pumps:
        out.append({"category": "filter", "title": "Clean irrigation filter", "subject_kind": "system", "subject_id": "", "interval_days": 30})
    for t in tanks:
        if t.float_sensor_id and t.float_sensor_id in {x.id for x in sensors}:  # only a REAL float switch needs testing
            out.append({"category": "safety", "title": f"Test low-level cut-out (lift the float): {t.name}", "subject_kind": "tank", "subject_id": t.id, "interval_days": 90})
    if acts:
        out.append({"category": "safety", "title": "Test the hardware emergency stop", "subject_kind": "system", "subject_id": "", "interval_days": 90})
    if sensors or acts:
        out.append({"category": "backup", "title": "Make a backup and test restoring it", "subject_kind": "system", "subject_id": "", "interval_days": 90})
    out.append({"category": "storage", "title": "Check storage health and free space", "subject_kind": "system", "subject_id": "", "interval_days": 30})
    for o in out:
        o["id"] = _task_id(o["title"], o["subject_id"])
        o["basis"] = "starting suggestion: adjust to your equipment and the manufacturer's instructions"
    return out


def mark_done(db: Database, task_id: str, note: str, now: float | None = None) -> bool:
    now = int(time.time() if now is None else now)
    with db.session() as s:
        t = s.get(MaintenanceTask, task_id)
        if t is None:
            return False
        t.last_done_ts = now
        s.add(MaintenanceLog(task_id=task_id, ts=now, note=note))
    return True


def check_alerts(db: Database, now: float | None = None) -> dict:
    """One alert per overdue task; cleared when the task is done or no longer overdue."""
    now = time.time() if now is None else now
    over = 0
    with db.session() as s:
        tasks = list(s.scalars(select(MaintenanceTask)))
    for t in tasks:
        st = status_of(t, now)["status"]
        if st == "overdue":
            over += 1
            events.raise_alert(db, "warning", "maintenance_due", t.id, f"Maintenance overdue: {t.title}")
        else:
            events.clear_alert(db, "maintenance_due", t.id)
    return {"overdue": over, "tasks": len(tasks)}
