from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.services import events, wizard

router = APIRouter(prefix="/api/wizard")


@router.get("")
def get_wizard(request: Request):
    return wizard.build(request.app)


class MarkIn(BaseModel):
    note: str


@router.post("/{step_id}/confirm")
def confirm(step_id: str, body: MarkIn, request: Request):
    try:
        wizard.mark(request.app.state.db, step_id, body.note)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    events.log_event(request.app.state.db, "info", "wizard", f"Step '{step_id}' confirmed by user: {body.note[:100]}")
    return {"ok": True}


@router.delete("/{step_id}/confirm")
def unconfirm(step_id: str, request: Request):
    wizard.unmark(request.app.state.db, step_id)
    return {"ok": True}
