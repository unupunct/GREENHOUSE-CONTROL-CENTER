from __future__ import annotations

import csv
import io
import time
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlalchemy import select

from app.analytics import report, stats
from app.api.knowledge import load_profile
from app.core.models import CropBatch, Measurement, Sensor

router = APIRouter(prefix="/api/analytics")


def _db(r: Request):
    return r.app.state.db


def _profile(request: Request, crop_id: str | None):
    """Profile of an explicit crop, else of the newest active batch (if any)."""
    db = _db(request)
    if crop_id is None:
        with db.session() as s:
            b = s.scalars(select(CropBatch).where(CropBatch.status == "active").order_by(CropBatch.planted_on.desc())).first()
            crop_id = b.crop_id if b else None
    if crop_id is None:
        return None
    r = load_profile(db, crop_id)
    if r is None:
        raise HTTPException(404, f"unknown crop '{crop_id}'")
    return r[0]


def _anchor(d: str | None) -> date:
    try:
        return date.fromisoformat(d) if d else date.today()
    except ValueError:
        raise HTTPException(422, "date must be YYYY-MM-DD") from None


@router.get("/dli")
def dli(request: Request, days: int = Query(30, ge=1, le=3660), sensor_id: str | None = None, crop_id: str | None = None):
    db = _db(request)
    ids = [sensor_id] if sensor_id else stats.sensor_ids(db, "greenhouse", "par")
    if sensor_id:
        with db.session() as s:
            x = s.get(Sensor, sensor_id)
            if x is None or x.kind != "par":
                raise HTTPException(422, "sensor_id must be an existing PAR sensor")
    until = int(time.time()) + 1
    rows = stats.dli_by_day(db, ids, until - days * 86400, until)
    prof = _profile(request, crop_id)
    target = prof["light"]["dli_mol_m2_day"] if prof else None
    for r in rows:
        r["status"] = None if target is None or not r["complete"] else (
            "low" if r["dli_mol_m2"] < target["min"] else "high" if r["dli_mol_m2"] > target["max"] else "in_range")
    return {"days": rows, "target": target, "crop": prof["name"] if prof else None, "sensors": ids,
            "note": "DLI = PAR sensor integrated over the local day. Incomplete days (<90% coverage) are not judged."}


@router.get("/vpd")
def vpd(request: Request, hours: float = Query(24, gt=0, le=24 * 366), crop_id: str | None = None, max_points: int = 400):
    db = _db(request)
    until = int(time.time()) + 1
    since = int(until - hours * 3600)
    temp = stats.series(db, stats.sensor_ids(db, "greenhouse", "temperature"), since, until)
    rh = stats.series(db, stats.sensor_ids(db, "greenhouse", "humidity"), since, until)
    v = stats.vpd_series(temp, rh)
    pts = sorted(v.items())
    if len(pts) > max_points:
        size = -(-len(pts) // max_points)
        pts = [(c[len(c) // 2][0], sum(x for _, x in c) / len(c)) for c in (pts[i:i + size] for i in range(0, len(pts), size))]
    prof = _profile(request, crop_id)
    band = prof["vpd_kpa"] if prof else None
    return {"points": [{"ts": t, "value": round(x, 3)} for t, x in pts], "target": band, "crop": prof["name"] if prof else None,
            "in_band": stats.band_share(v, band["min"], band["max"]) if band else None}


@router.get("/report")
def get_report(request: Request, period: Literal["day", "week", "month"] = "day", date_: str | None = Query(None, alias="date"),
               crop_id: str | None = None):
    return report.build(_db(request), period, _anchor(date_), _profile(request, crop_id),
                        request.app.state.settings.flush_interval_s)


@router.get("/report.{fmt}")
def report_file(fmt: Literal["csv", "pdf"], request: Request, period: Literal["day", "week", "month"] = "day",
                date_: str | None = Query(None, alias="date"), crop_id: str | None = None):
    rep = report.build(_db(request), period, _anchor(date_), _profile(request, crop_id), request.app.state.settings.flush_interval_s)
    body, mime = (report.to_csv(rep), "text/csv") if fmt == "csv" else (report.to_pdf(rep), "application/pdf")
    return Response(body, media_type=mime, headers={
        "Content-Disposition": f'attachment; filename="greenhouse-{period}-{rep["start"]}.{fmt}"'})


METRICS = {"temperature": ("greenhouse", "temperature"), "humidity": ("greenhouse", "humidity"), "co2": ("greenhouse", "co2"),
           "outdoor_temperature": ("outdoor", "temperature")}


@router.get("/seasonal")
def seasonal(request: Request, metric: Literal["temperature", "humidity", "co2", "outdoor_temperature", "dli"] = "temperature"):
    """Monthly means per year, for comparing the same month across years/seasons. Only months with data appear."""
    db = _db(request)
    if metric == "dli":
        rows = stats.dli_by_day(db, stats.sensor_ids(db, "greenhouse", "par"), 0, int(time.time()) + 1)
        acc: dict[str, dict[str, list[float]]] = {}
        for r in rows:
            if r["complete"]:
                y, m = r["date"][:4], r["date"][5:7]
                acc.setdefault(y, {}).setdefault(m, []).append(r["dli_mol_m2"])
        data = {y: {m: round(sum(v) / len(v), 3) for m, v in sorted(mm.items())} for y, mm in sorted(acc.items())}
    else:
        zone, kind = METRICS[metric]
        data = stats.monthly_means(db, stats.sensor_ids(db, zone, kind))
    return {"metric": metric, "monthly_means": data,
            "note": "Mean of stored samples per local month. Months without data are absent; data older than the retention period is deleted."}


@router.get("/export/measurements.csv")
def export_measurements(request: Request, sensor_id: str, days: float = Query(7, gt=0, le=3660)):
    db = _db(request)
    since = int(time.time() - days * 86400)
    with db.session() as s:
        sensor = s.get(Sensor, sensor_id)
        if sensor is None:
            raise HTTPException(404, "unknown sensor")
        rows = s.execute(select(Measurement.ts, Measurement.value).where(
            Measurement.sensor_id == sensor_id, Measurement.ts >= since).order_by(Measurement.ts)).all()
        unit = sensor.unit
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["timestamp_utc", "timestamp_local", f"value_{unit or 'unit'}"])
    for ts, v in rows:
        w.writerow([time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)), time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)), v])
    return Response(("﻿" + buf.getvalue()).encode("utf-8"), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{sensor_id}-{int(days)}d.csv"'})
