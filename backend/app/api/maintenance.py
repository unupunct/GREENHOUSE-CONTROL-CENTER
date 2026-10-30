from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.models import Actuator, MaintenanceLog, MaintenanceTask, Replacement, Sensor, Tank
from app.services import events, maintenance as m

router = APIRouter(prefix="/api/maintenance")
ID = r"^[a-z0-9_]{2,48}$"
Cat = Literal["calibration", "filter", "pump", "valve", "fan", "window", "safety", "battery", "storage", "backup", "other"]


def _db(r: Request):
    return r.app.state.db


class TaskIn(BaseModel):
    id: str | None = Field(None, pattern=ID)
    title: str = Field(min_length=3, max_length=160)
    category: Cat = "other"
    subject_kind: Literal["sensor", "actuator", "tank", "system"] = "system"
    subject_id: str = Field("", max_length=64)
    interval_days: int = Field(gt=0, le=3650)
    enabled: bool = True
    notes: str = ""


def _check_subject(db, kind: str, sid: str) -> None:
    if kind == "system":
        return
    model = {"sensor": Sensor, "actuator": Actuator, "tank": Tank}[kind]
    with db.session() as s:
        if not sid or s.get(model, sid) is None:
            raise HTTPException(422, f"unknown {kind} '{sid}'")


@router.get("")
def list_tasks(request: Request):
    now = time.time()
    with _db(request).session() as s:
        tasks = list(s.scalars(select(MaintenanceTask)))
    rows = sorted((m.task_dict(t, now) for t in tasks), key=lambda r: r["next_due_ts"])
    return {"tasks": rows, "overdue": sum(r["status"] == "overdue" for r in rows), "due_soon": sum(r["status"] == "due_soon" for r in rows),
            "categories": m.CATEGORIES}


@router.post("", status_code=201)
def create_task(body: TaskIn, request: Request):
    _check_subject(_db(request), body.subject_kind, body.subject_id)
    tid = body.id or m._task_id(body.title, body.subject_id)
    with _db(request).session() as s:
        if s.get(MaintenanceTask, tid):
            raise HTTPException(409, f"task '{tid}' already exists")
        s.add(MaintenanceTask(id=tid, title=body.title, category=body.category, subject_kind=body.subject_kind, subject_id=body.subject_id,
                              interval_days=body.interval_days, created_at=int(time.time()), enabled=body.enabled, notes=body.notes))
    return {"id": tid}


@router.put("/{task_id}")
def update_task(task_id: str, body: TaskIn, request: Request):
    _check_subject(_db(request), body.subject_kind, body.subject_id)
    with _db(request).session() as s:
        t = s.get(MaintenanceTask, task_id)
        if t is None:
            raise HTTPException(404, "not found")
        t.title, t.category, t.subject_kind, t.subject_id = body.title, body.category, body.subject_kind, body.subject_id
        t.interval_days, t.enabled, t.notes = body.interval_days, body.enabled, body.notes
    return {"ok": True}


@router.delete("/{task_id}")
def delete_task(task_id: str, request: Request):
    with _db(request).session() as s:
        t = s.get(MaintenanceTask, task_id)
        if t is None:
            raise HTTPException(404, "not found")
        s.delete(t)
        for lg in s.scalars(select(MaintenanceLog).where(MaintenanceLog.task_id == task_id)):
            s.delete(lg)
    events.clear_alert(_db(request), "maintenance_due", task_id)
    return {"ok": True}


class DoneIn(BaseModel):
    note: str = Field("", max_length=1000)


@router.post("/{task_id}/done")
def done(task_id: str, body: DoneIn, request: Request):
    if not m.mark_done(_db(request), task_id, body.note):
        raise HTTPException(404, "not found")
    events.clear_alert(_db(request), "maintenance_due", task_id)
    events.log_event(_db(request), "info", "maintenance", f"Task '{task_id}' done" + (f": {body.note[:100]}" if body.note else ""))
    return {"ok": True}


@router.get("/{task_id}/log")
def task_log(task_id: str, request: Request):
    with _db(request).session() as s:
        rows = s.scalars(select(MaintenanceLog).where(MaintenanceLog.task_id == task_id).order_by(MaintenanceLog.id.desc()).limit(100)).all()
    return [{"ts": r.ts, "note": r.note} for r in rows]


@router.get("/suggestions/list")
def suggestions(request: Request):
    existing = {t["id"] for t in list_tasks(request)["tasks"]}
    sug = m.suggestions(_db(request))
    return {"suggestions": [{**x, "exists": x["id"] in existing} for x in sug],
            "note": "Built from your real (non-simulated) equipment. Intervals are starting suggestions: adjust them."}


class ApplyIn(BaseModel):
    ids: list[str] | None = None


@router.post("/suggestions/apply")
def apply_suggestions(body: ApplyIn, request: Request):
    made = []
    now = int(time.time())
    with _db(request).session() as s:
        for x in m.suggestions(_db(request)):
            if (body.ids is not None and x["id"] not in body.ids) or s.get(MaintenanceTask, x["id"]):
                continue
            s.add(MaintenanceTask(id=x["id"], title=x["title"], category=x["category"], subject_kind=x["subject_kind"],
                                  subject_id=x["subject_id"], interval_days=x["interval_days"], created_at=now, notes=x["basis"]))
            made.append(x["id"])
    return {"created": made}


@router.post("/check")
def run_check(request: Request):
    return m.check_alerts(_db(request))


# ------------------------------------------------- replacement history

class ReplacementIn(BaseModel):
    subject_kind: Literal["sensor", "actuator", "tank", "system", "other"]
    subject_id: str = Field(min_length=1, max_length=64)
    reason: str = Field("", max_length=160)
    old_item: str = Field("", max_length=160)
    new_item: str = Field("", max_length=160)
    note: str = ""
    ts: int | None = None


@router.post("/replacements", status_code=201)
def add_replacement(body: ReplacementIn, request: Request):
    with _db(request).session() as s:
        r = Replacement(**{**body.model_dump(), "ts": body.ts or int(time.time())})
        s.add(r)
        s.flush()
        rid = r.id
    events.log_event(_db(request), "info", "maintenance", f"Replacement recorded for {body.subject_kind} '{body.subject_id}'")
    return {"id": rid}


@router.get("/replacements/list")
def list_replacements(request: Request, subject_id: str | None = None):
    with _db(request).session() as s:
        q = select(Replacement).order_by(Replacement.ts.desc())
        if subject_id:
            q = q.where(Replacement.subject_id == subject_id)
        rows = s.scalars(q.limit(500)).all()
    return [{"id": r.id, "ts": r.ts, "subject_kind": r.subject_kind, "subject_id": r.subject_id, "reason": r.reason,
             "old_item": r.old_item, "new_item": r.new_item, "note": r.note} for r in rows]


@router.delete("/replacements/{rid}")
def delete_replacement(rid: int, request: Request):
    with _db(request).session() as s:
        r = s.get(Replacement, rid)
        if r is None:
            raise HTTPException(404, "not found")
        s.delete(r)
    return {"ok": True}
