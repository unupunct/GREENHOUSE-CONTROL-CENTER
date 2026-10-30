from __future__ import annotations

import json
import time
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select

from app import __version__
from app.core.models import Alert, Event, Measurement, MeasurementHourly, Sensor
from app.services import climate, system_info
from app.services.greenhouse_config import (
    GreenhouseConfig,
    engineering_inputs,
    load_config,
    save_config,
)

router = APIRouter(prefix="/api")


def _db(request: Request):
    return request.app.state.db


def _config_payload(cfg: GreenhouseConfig) -> dict:
    d = cfg.model_dump(mode="json")
    d["area_m2"] = cfg.area_m2
    d["volume_m3"] = cfg.volume_m3
    return d


@router.get("/health")
def health(request: Request):
    db = _db(request)
    integrity = db.integrity_check()
    return {"status": "ok" if integrity == "ok" else "degraded", "version": __version__,
            "database": integrity, "simulated": request.app.state.settings.simulate}


@router.get("/config")
def get_config(request: Request):
    return _config_payload(load_config(_db(request)))


@router.put("/config")
def put_config(cfg: GreenhouseConfig, request: Request):
    save_config(_db(request), cfg)
    from app.services.events import log_event
    log_event(_db(request), "info", "config", "Greenhouse configuration updated")
    return _config_payload(cfg)


@router.get("/config/engineering-inputs")
def get_engineering_inputs(request: Request):
    items = engineering_inputs(load_config(_db(request)))
    return {"missing": sum(not i.provided for i in items),
            "items": [i.model_dump() for i in items]}


def _status(ts: int | None, poll_s: float) -> str:
    if ts is None:
        return "no_data"
    return "ok" if time.time() - ts <= max(3 * poll_s, 15) else "stale"


@router.get("/sensors")
def list_sensors(request: Request):
    ingest = request.app.state.ingest
    poll = request.app.state.settings.poll_interval_s
    with _db(request).session() as s:
        rows = s.scalars(select(Sensor).order_by(Sensor.zone, Sensor.id)).all()
    out = []
    for r in rows:
        lv = ingest.latest.get(r.id)
        out.append({
            "id": r.id, "name": r.name, "kind": r.kind, "zone": r.zone, "unit": r.unit,
            "driver": r.driver, "protocol": r.protocol, "simulated": r.simulated,
            "enabled": r.enabled, "address": json.loads(r.address or "{}"),
            "min_valid": r.min_valid, "max_valid": r.max_valid,
            "cal_offset": r.cal_offset, "cal_gain": r.cal_gain, "calibrated_at": r.calibrated_at,
            "value": lv.value if lv else None, "raw": lv.raw if lv else None,
            "ts": lv.ts if lv else None,
            "status": _status(lv.ts if lv else None, poll) if r.enabled else "disabled",
        })
    return out


def _bucket(points: list[tuple[int, float]], max_points: int) -> list[dict]:
    if len(points) <= max_points:
        return [{"ts": t, "value": v} for t, v in points]
    size = -(-len(points) // max_points)
    out = []
    for i in range(0, len(points), size):
        chunk = points[i:i + size]
        out.append({"ts": chunk[len(chunk) // 2][0],
                    "value": round(sum(v for _, v in chunk) / len(chunk), 3)})
    return out


@router.get("/readings/history")
def history(request: Request, sensor_id: str,
            hours: float = Query(24, gt=0, le=24 * 366),
            max_points: int = Query(300, ge=10, le=2000)):
    until = int(time.time()) + 1
    since = int(until - hours * 3600)
    bucket = max(1, -(-(until - since) // max_points))
    with _db(request).session() as s:
        if s.get(Sensor, sensor_id) is None:
            raise HTTPException(404, f"unknown sensor '{sensor_id}'")
        oldest = s.scalar(select(func.min(Measurement.ts)).where(Measurement.sensor_id == sensor_id))
        if bucket <= 60:  # at most one raw sample per bucket anyway
            raw = s.execute(select(Measurement.ts, Measurement.value).where(
                Measurement.sensor_id == sensor_id, Measurement.ts >= since).order_by(Measurement.ts)).all()
            pts = [(r[0], r[1]) for r in raw]
        else:      # bucket averaging done by SQLite: bounded memory however long the range
            q = select(func.avg(Measurement.ts), func.avg(Measurement.value)).where(
                Measurement.sensor_id == sensor_id, Measurement.ts >= since).group_by(Measurement.ts.op("/")(bucket)).order_by(func.min(Measurement.ts))
            pts = [(int(a), float(b)) for a, b in s.execute(q)]
        if oldest is None or since < oldest:  # older than the raw samples: use the hourly roll-ups
            end = oldest if oldest is not None else until
            hourly = s.execute(select(MeasurementHourly.hour_ts, MeasurementHourly.vavg).where(
                MeasurementHourly.sensor_id == sensor_id, MeasurementHourly.hour_ts >= since - 3600, MeasurementHourly.hour_ts + 3600 <= end
            ).order_by(MeasurementHourly.hour_ts)).all()
            pts = [(h + 1800, v) for h, v in hourly] + pts
    return {"sensor_id": sensor_id, "points": _bucket(pts, max_points)}


def _mean_by_ts(rows) -> dict[int, float]:
    acc: dict[int, list[float]] = defaultdict(list)
    for ts, v in rows:
        acc[ts].append(v)
    return {ts: sum(v) / len(v) for ts, v in acc.items()}


@router.get("/climate/vpd")
def vpd_latest(request: Request):
    ingest = request.app.state.ingest
    with _db(request).session() as s:
        gh = s.scalars(select(Sensor).where(Sensor.zone == "greenhouse")).all()
    t = [ingest.latest[x.id].value for x in gh if x.kind == "temperature" and x.id in ingest.latest]
    h = [ingest.latest[x.id].value for x in gh if x.kind == "humidity" and x.id in ingest.latest]
    if not t or not h:
        return {"available": False}
    temp, rh = sum(t) / len(t), sum(h) / len(h)
    return {"available": True, "temperature_c": round(temp, 2), "humidity_percent": round(rh, 1),
            "vpd_kpa": round(climate.vpd_kpa(temp, rh), 3),
            "dew_point_c": round(climate.dew_point_c(temp, rh), 2),
            "assumption": "Leaf temperature assumed equal to air temperature; "
                          "mean of all greenhouse air sensors."}


@router.get("/climate/vpd/history")
def vpd_history(request: Request, hours: float = Query(24, gt=0, le=24 * 366),
                max_points: int = Query(300, ge=10, le=2000)):
    since = int(time.time() - hours * 3600)
    with _db(request).session() as s:
        ids = s.execute(select(Sensor.id, Sensor.kind).where(Sensor.zone == "greenhouse")).all()
        t_ids = [i for i, k in ids if k == "temperature"]
        h_ids = [i for i, k in ids if k == "humidity"]
        def q(sel):
            return s.execute(select(Measurement.ts, Measurement.value).where(
                Measurement.sensor_id.in_(sel), Measurement.ts >= since)).all()
        temps, hums = _mean_by_ts(q(t_ids)), _mean_by_ts(q(h_ids))
    pts = [(ts, round(climate.vpd_kpa(temps[ts], hums[ts]), 3)) for ts in sorted(temps) if ts in hums]
    return {"points": _bucket(pts, max_points)}


@router.get("/events")
def list_events(request: Request, limit: int = Query(100, ge=1, le=1000)):
    with _db(request).session() as s:
        rows = s.scalars(select(Event).order_by(Event.id.desc()).limit(limit)).all()
    return [{"id": e.id, "ts": e.ts, "level": e.level, "source": e.source,
             "message": e.message} for e in rows]


@router.get("/alerts")
def list_alerts(request: Request, active_only: bool = True):
    with _db(request).session() as s:
        q = select(Alert).order_by(Alert.id.desc()).limit(200)
        if active_only:
            q = q.where(Alert.active.is_(True))
        rows = s.scalars(q).all()
    return [{"id": a.id, "ts": a.ts, "severity": a.severity, "code": a.code,
             "subject": a.subject, "message": a.message, "active": a.active,
             "acknowledged": a.acknowledged} for a in rows]


@router.post("/alerts/{alert_id}/ack")
def ack_alert(alert_id: int, request: Request):
    with _db(request).session() as s:
        a = s.get(Alert, alert_id)
        if a is None:
            raise HTTPException(404, "alert not found")
        a.acknowledged = True
    return {"ok": True}


@router.get("/system")
def system(request: Request):
    s = request.app.state.settings
    return {**system_info.collect(s.data_dir), "database_path": str(s.db_path),
            "retention_days": s.retention_days, "flush_interval_s": s.flush_interval_s,
            "version": __version__}


