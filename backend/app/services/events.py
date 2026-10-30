"""Event log and alert helpers."""

from __future__ import annotations

import time

from sqlalchemy import select

from app.core.db import Database
from app.core.models import Alert, Event


def log_event(db: Database, level: str, source: str, message: str) -> None:
    with db.session() as s:
        s.add(Event(ts=int(time.time()), level=level, source=source, message=message))


def raise_alert(db: Database, severity: str, code: str, subject: str, message: str) -> bool:
    """Open an alert unless an active one with the same code+subject exists."""
    with db.session() as s:
        existing = s.scalar(select(Alert).where(
            Alert.code == code, Alert.subject == subject, Alert.active.is_(True)))
        if existing:
            return False
        s.add(Alert(ts=int(time.time()), severity=severity, code=code,
                    subject=subject, message=message))
        return True


def clear_alert(db: Database, code: str, subject: str) -> None:
    with db.session() as s:
        for a in s.scalars(select(Alert).where(
                Alert.code == code, Alert.subject == subject, Alert.active.is_(True))):
            a.active = False


def prune(db: Database, retention_days: int, now: float | None = None) -> dict:
    """Old events, audit entries and resolved alerts are deleted so these tables cannot grow forever."""
    from sqlalchemy import delete

    from app.core.models import Alert, AuditLog, Event
    cutoff = int((time.time() if now is None else now) - retention_days * 86400)
    with db.session() as s:
        e = s.execute(delete(Event).where(Event.ts < cutoff)).rowcount or 0
        a = s.execute(delete(AuditLog).where(AuditLog.ts < cutoff)).rowcount or 0
        al = s.execute(delete(Alert).where(Alert.ts < cutoff, Alert.active.is_(False))).rowcount or 0
    return {"events": e, "audit": a, "alerts": al}
