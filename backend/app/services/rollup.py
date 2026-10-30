"""Hourly roll-ups: raw samples are pruned after ``retention_days``, hourly summaries live much longer
(seasonal and year-on-year comparison, long history charts) at a tiny fraction of the storage."""

from __future__ import annotations

import time

from sqlalchemy import delete, text

from app.core.db import Database
from app.core.models import AppSetting, Measurement, MeasurementHourly

KEY = "rollup_until"


def rolled_until(db: Database) -> int:
    with db.session() as s:
        row = s.get(AppSetting, KEY)
        return int(row.value) if row else 0


def _set_until(db: Database, ts: int) -> None:
    with db.session() as s:
        row = s.get(AppSetting, KEY)
        if row is None:
            s.add(AppSetting(key=KEY, value=str(ts), updated_at=int(time.time())))
        else:
            row.value, row.updated_at = str(ts), int(time.time())


def roll(db: Database, now: float | None = None) -> int:
    """Summarise every COMPLETE hour not yet summarised. Existing summaries are never overwritten."""
    now = time.time() if now is None else now
    until = int(now // 3600 * 3600)
    start = rolled_until(db)
    if start >= until:
        return 0
    with db.session() as s:
        r = s.execute(text(
            "INSERT OR IGNORE INTO measurement_hourly (sensor_id, hour_ts, n, vmin, vmax, vavg) "
            "SELECT sensor_id, (ts / 3600) * 3600, COUNT(*), MIN(value), MAX(value), AVG(value) FROM measurements "
            "WHERE ts >= :a AND ts < :b GROUP BY sensor_id, ts / 3600"), {"a": start, "b": until})
        n = r.rowcount or 0
    _set_until(db, until)
    return n


def prune(db: Database, settings, now: float | None = None) -> int:
    """Roll up, then delete raw samples older than the retention (aligned to whole hours so no hour is split)."""
    now = time.time() if now is None else now
    roll(db, now)
    cutoff = int((now - settings.retention_days * 86400) // 3600 * 3600)
    cutoff = min(cutoff, rolled_until(db))  # never delete samples that are not summarised yet
    with db.session() as s:
        n = s.execute(delete(Measurement).where(Measurement.ts < cutoff)).rowcount or 0
        s.execute(delete(MeasurementHourly).where(MeasurementHourly.hour_ts < now - settings.rollup_retention_days * 86400))
    if n > 5000:  # give the space back to the file only after a big clean-up
        try:
            with db.engine.connect() as c:
                c.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:  # noqa: BLE001
            pass
    return n
