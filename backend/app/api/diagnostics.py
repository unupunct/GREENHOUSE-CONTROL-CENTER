from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.models import Alert, Event
from app.services import diagnostics as d
from app.services import troubleshoot

router = APIRouter(prefix="/api/diagnostics")


@router.get("/health")
def health(request: Request):
    return d.health(request.app)


@router.get("/settings")
def get_settings(request: Request):
    return d.load_settings(request.app.state.db).model_dump()


@router.put("/settings")
def put_settings(body: d.DiagSettings, request: Request):
    if body.cpu_temp_warn_c >= body.cpu_temp_crit_c:
        raise HTTPException(422, "CPU warning temperature must be below the critical temperature")
    d.save_settings(request.app.state.db, body)
    return body.model_dump()


@router.post("/run")
def run_now(request: Request):
    """Evaluate health thresholds and maintenance now (also done hourly)."""
    from app.services import maintenance
    d.sync_health_alerts(request.app)
    return {"maintenance": maintenance.check_alerts(request.app.state.db), "health": d.health(request.app)["overall"]}


@router.get("/comms")
def comms(request: Request):
    return d.comms(request.app)


@router.get("/errors")
def errors(request: Request, days: float = Query(7, gt=0, le=366), level: str | None = None, source: str | None = None, limit: int = 300):
    return {"events": [{**e, "explanation": troubleshoot.explain(e["message"]) if e["level"] in ("error", "warning") else None}
                       for e in d.errors(request.app.state.db, days, level, source, limit)]}


class ExplainIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@router.post("/explain")
def explain(body: ExplainIn):
    return troubleshoot.explain(body.text)


@router.get("/explain/active")
def explain_active(request: Request):
    """Plain-English explanations of every active alert and of recent errors/warnings (last 24 h)."""
    db = request.app.state.db
    with db.session() as s:
        alerts = list(s.scalars(select(Alert).where(Alert.active.is_(True)).order_by(Alert.id.desc())))
        evs = list(s.scalars(select(Event).where(Event.ts >= int(time.time()) - 86400, Event.level.in_(["error", "warning"])).order_by(Event.id.desc()).limit(30)))
    return {"alerts": [{"id": a.id, "severity": a.severity, "code": a.code, "subject": a.subject, "message": a.message,
                        "explanation": troubleshoot.explain(a.message)} for a in alerts],
            "recent": [{"ts": e.ts, "source": e.source, "message": e.message, "explanation": troubleshoot.explain(e.message)} for e in evs]}


class DiagnoseIn(BaseModel):
    kind: Literal["sensor", "output", "zone", "window"]
    id: str = Field(min_length=1, max_length=64)


@router.post("/diagnose")
def diagnose(body: DiagnoseIn, request: Request):
    """Checks the live system for the likely reasons something is not working."""
    return d.diagnose(request.app, body.kind, body.id)
