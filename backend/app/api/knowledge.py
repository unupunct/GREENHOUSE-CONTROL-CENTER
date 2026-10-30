from __future__ import annotations

import json
import re
import time
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.automation.climate_rules import in_time_window
from app.core.models import CropBatch, Harvest, PlantUser, Sensor
from app.knowledge import plants
from app.services import climate

router = APIRouter(prefix="/api")
ID = r"^[a-z0-9_]{2,48}$"


def _db(r: Request):
    return r.app.state.db


def _user_rows(db) -> dict[str, PlantUser]:
    with db.session() as s:
        return {u.crop_id: u for u in s.scalars(select(PlantUser))}


def load_profile(db, crop_id: str) -> tuple[dict, list[str]] | None:
    """Merged profile and the list of user-changed field paths."""
    rows = _user_rows(db)
    u = rows.get(crop_id)
    if u and u.custom:
        p = json.loads(u.data)
        return p, ["(custom crop: all fields are yours)"]
    base = plants.get_builtin(crop_id)
    if base is None:
        return None
    if u:
        patch = json.loads(u.data)
        return plants.deep_merge(base, patch), plants.changed_paths(patch)
    return base, []


def _all_ids(db) -> list[str]:
    ids = list(plants.PROFILES)
    ids += [k for k, u in _user_rows(db).items() if u.custom and k not in ids]
    return ids


@router.get("/plants")
def list_plants(request: Request):
    out = []
    for cid in _all_ids(_db(request)):
        p, changed = load_profile(_db(request), cid)
        out.append({"id": cid, "name": p["name"], "latin": p.get("latin", ""), "category": p.get("category", ""),
                    "custom": bool(p.get("custom")), "modified": bool(changed)})
    return {"plants": out, "provenance": plants.PROVENANCE}


@router.get("/plants/{crop_id}")
def get_plant(crop_id: str, request: Request):
    r = load_profile(_db(request), crop_id)
    if r is None:
        raise HTTPException(404, "unknown crop")
    p, changed = r
    return {"profile": p, "user_changed_fields": changed,
            "provenance": "Your own profile" if p.get("custom") else plants.PROVENANCE}


@router.put("/plants/{crop_id}/override")
def put_override(crop_id: str, patch: dict, request: Request):
    """Change values of a built-in crop. ``patch`` is a partial profile (nested)."""
    if crop_id not in plants.PROFILES:
        raise HTTPException(404, "not a built-in crop (custom crops are replaced with PUT /api/plants/{id})")
    patch = {k: v for k, v in patch.items() if k not in ("id", "custom")}
    errs = plants.validate_profile(patch, partial=True)
    merged = plants.deep_merge(plants.PROFILES[crop_id], patch)
    errs += plants.validate_profile(merged)
    if errs:
        raise HTTPException(422, "; ".join(dict.fromkeys(errs)))
    with _db(request).session() as s:
        u = s.get(PlantUser, crop_id)
        if u is not None and not u.custom:
            patch = plants.deep_merge(json.loads(u.data), patch)
        s.merge(PlantUser(crop_id=crop_id, data=json.dumps(patch), custom=False, updated_at=int(time.time())))
    return {"ok": True, "changed": plants.changed_paths(patch)}


@router.delete("/plants/{crop_id}/override")
def reset_override(crop_id: str, request: Request):
    with _db(request).session() as s:
        u = s.get(PlantUser, crop_id)
        if u is None or u.custom:
            raise HTTPException(404, "no override to remove")
        s.delete(u)
    return {"ok": True}


@router.put("/plants/{crop_id}")
def put_custom(crop_id: str, profile: dict, request: Request):
    """Create or replace a CUSTOM crop (complete profile). Built-in ids are protected."""
    if not re.fullmatch(ID, crop_id):
        raise HTTPException(422, "id must be a-z 0-9 _ (2-48 chars)")
    if crop_id in plants.PROFILES:
        raise HTTPException(409, "built-in crop id: use /override or pick another id")
    profile = {**profile, "id": crop_id, "custom": True}
    full = plants.deep_merge(plants.get_builtin("tomato"), {})  # structural defaults
    for k in ("pests", "diseases", "growth_stages"):
        full[k] = []
    full["water"] = dict(plants.WATER)
    full = plants.deep_merge(full, profile)
    errs = plants.validate_profile(full)
    if errs:
        raise HTTPException(422, "; ".join(dict.fromkeys(errs)))
    with _db(request).session() as s:
        s.merge(PlantUser(crop_id=crop_id, data=json.dumps(full), custom=True, updated_at=int(time.time())))
    return {"ok": True}


@router.delete("/plants/{crop_id}")
def delete_custom(crop_id: str, request: Request):
    with _db(request).session() as s:
        u = s.get(PlantUser, crop_id)
        if u is None or not u.custom:
            raise HTTPException(404, "not a custom crop")
        if s.scalar(select(func.count()).select_from(CropBatch).where(CropBatch.crop_id == crop_id)):
            raise HTTPException(409, "crop batches use this crop")
        s.delete(u)
    return {"ok": True}


@router.get("/plants/{crop_id}/setpoints")
def suggest_setpoints(crop_id: str, request: Request, hysteresis_c: float = 1.0, fan_offset_c: float = 2.0):
    """Starting values for the climate setpoint template, derived from the profile.
    The hysteresis and fan offset are assumptions (parameters), not crop data."""
    r = load_profile(_db(request), crop_id)
    if r is None:
        raise HTTPException(404, "unknown crop")
    t = r[0]["temperature_c"]
    return {
        "day_heat_on_below": t["day_min"], "day_heat_off_above": round(t["day_min"] + hysteresis_c, 2),
        "night_heat_on_below": t["night_min"], "night_heat_off_above": round(t["night_min"] + hysteresis_c, 2),
        "vent_open_above": t["day_max"], "vent_close_below": round(t["day_max"] - hysteresis_c, 2),
        "fan_on_above": round(t["day_max"] + fan_offset_c, 2), "fan_off_below": round(t["day_max"] + fan_offset_c - hysteresis_c, 2),
        "basis": f"From the '{r[0]['name']}' profile (general guidance). Hysteresis {hysteresis_c} C and fan offset "
                 f"{fan_offset_c} C are assumptions. Review before use.",
    }


# ------------------------------------------------------------ crop batches

class BatchIn(BaseModel):
    id: str = Field(pattern=ID)
    crop_id: str
    label: str = Field("", max_length=120)
    method: Literal["soil", "hydroponic"]
    area_m2: float | None = Field(None, gt=0, le=100000)
    planted_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    stage: str = Field("", max_length=60)
    status: Literal["active", "harvested", "discarded"] = "active"
    notes: str = ""


def _batch(b: CropBatch, kg: float | None = None) -> dict:
    d = {c.name: getattr(b, c.name) for c in CropBatch.__table__.columns}
    if kg is not None:
        d["harvested_kg"] = round(kg, 3)
        d["yield_kg_per_m2"] = round(kg / b.area_m2, 3) if b.area_m2 else None
    return d


def _check_date(v: str) -> None:
    try:
        date.fromisoformat(v)
    except ValueError:
        raise HTTPException(422, f"invalid date '{v}'") from None


@router.get("/crops")
def list_batches(request: Request):
    with _db(request).session() as s:
        kg = dict(s.execute(select(Harvest.batch_id, func.sum(Harvest.quantity_kg)).group_by(Harvest.batch_id)).all())
        return [_batch(b, kg.get(b.id, 0.0)) for b in s.scalars(select(CropBatch).order_by(CropBatch.planted_on.desc()))]


@router.post("/crops", status_code=201)
def create_batch(body: BatchIn, request: Request):
    _check_date(body.planted_on)
    if load_profile(_db(request), body.crop_id) is None:
        raise HTTPException(422, f"unknown crop '{body.crop_id}'")
    with _db(request).session() as s:
        if s.get(CropBatch, body.id):
            raise HTTPException(409, "id already exists")
        s.add(CropBatch(**body.model_dump(), created_at=int(time.time())))
    return {"id": body.id}


@router.put("/crops/{batch_id}")
def update_batch(batch_id: str, body: BatchIn, request: Request):
    if body.id != batch_id:
        raise HTTPException(422, "id cannot be changed")
    _check_date(body.planted_on)
    with _db(request).session() as s:
        b = s.get(CropBatch, batch_id)
        if b is None:
            raise HTTPException(404, "not found")
        for k, v in body.model_dump().items():
            setattr(b, k, v)
    return {"ok": True}


@router.delete("/crops/{batch_id}")
def delete_batch(batch_id: str, request: Request):
    with _db(request).session() as s:
        b = s.get(CropBatch, batch_id)
        if b is None:
            raise HTTPException(404, "not found")
        s.delete(b)
        for h in s.scalars(select(Harvest).where(Harvest.batch_id == batch_id)):
            s.delete(h)
    return {"ok": True}


class HarvestIn(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    quantity_kg: float = Field(gt=0, le=1_000_000)
    notes: str = ""


@router.post("/crops/{batch_id}/harvests", status_code=201)
def add_harvest(batch_id: str, body: HarvestIn, request: Request):
    _check_date(body.date)
    with _db(request).session() as s:
        if s.get(CropBatch, batch_id) is None:
            raise HTTPException(404, "batch not found")
        h = Harvest(batch_id=batch_id, **body.model_dump())
        s.add(h)
        s.flush()
        return {"id": h.id}


@router.get("/crops/{batch_id}/harvests")
def list_harvests(batch_id: str, request: Request):
    with _db(request).session() as s:
        rows = s.scalars(select(Harvest).where(Harvest.batch_id == batch_id).order_by(Harvest.date)).all()
    return [{"id": h.id, "date": h.date, "quantity_kg": h.quantity_kg, "notes": h.notes} for h in rows]


@router.delete("/harvests/{harvest_id}")
def delete_harvest(harvest_id: int, request: Request):
    with _db(request).session() as s:
        h = s.get(Harvest, harvest_id)
        if h is None:
            raise HTTPException(404, "not found")
        s.delete(h)
    return {"ok": True}


# -------------------------------------------------- current conditions check

def _verdict(v: float | None, lo: float | None, hi: float | None) -> str:
    if v is None:
        return "no_data"
    if lo is not None and v < lo:
        return "low"
    if hi is not None and v > hi:
        return "high"
    return "in_range"


@router.get("/crops/{batch_id}/status")
def batch_status(batch_id: str, request: Request, day_start: str = "06:00", night_start: str = "20:00"):
    """Compare live readings with the batch's crop profile.
    Day/night is decided by clock time (day_start/night_start are parameters, not crop data)."""
    db = _db(request)
    with db.session() as s:
        b = s.get(CropBatch, batch_id)
        if b is None:
            raise HTTPException(404, "batch not found")
        sensors = list(s.scalars(select(Sensor).where(Sensor.enabled.is_(True))))
        crop_id, method = b.crop_id, b.method
    prof = load_profile(db, crop_id)
    if prof is None:
        raise HTTPException(404, "crop profile missing")
    p = prof[0]
    latest = request.app.state.ingest.latest
    max_age = max(3 * request.app.state.settings.poll_interval_s, 15)
    now = time.time()

    def mean(zone: str, kind: str):
        vals = [latest[x.id].value for x in sensors if x.zone == zone and x.kind == kind and x.id in latest
                and now - latest[x.id].ts <= max_age]
        return sum(vals) / len(vals) if vals else None

    lt = time.localtime(now)
    is_day = in_time_window(lt.tm_hour * 60 + lt.tm_min, day_start, night_start)
    t = p["temperature_c"]
    lo, hi = (t["day_min"], t["day_max"]) if is_day else (t["night_min"], t["night_max"])
    temp, rh = mean("greenhouse", "temperature"), mean("greenhouse", "humidity")
    vpd = climate.vpd_kpa(temp, rh) if temp is not None and rh is not None else None
    checks = [
        {"name": f"Air temperature ({'day' if is_day else 'night'})", "value": None if temp is None else round(temp, 1),
         "unit": "C", "min": lo, "max": hi, "status": _verdict(temp, lo, hi)},
        {"name": "Relative humidity", "value": None if rh is None else round(rh, 1), "unit": "%",
         "min": p["humidity_rh"]["min"], "max": p["humidity_rh"]["max"], "status": _verdict(rh, p["humidity_rh"]["min"], p["humidity_rh"]["max"])},
        {"name": "VPD", "value": None if vpd is None else round(vpd, 2), "unit": "kPa",
         "min": p["vpd_kpa"]["min"], "max": p["vpd_kpa"]["max"], "status": _verdict(vpd, p["vpd_kpa"]["min"], p["vpd_kpa"]["max"])},
    ]
    if method == "hydroponic":
        h = p["hydroponic"]
        for name, kind, key, unit in (("Solution pH", "ph", "ph", ""), ("Solution EC", "ec", "ec_ms_cm", "mS/cm"),
                                      ("Solution temperature", "temperature", "solution_temp_c", "C")):
            rr = h.get(key)
            v = mean("hydroponic", kind)
            checks.append({"name": name, "value": None if v is None else round(v, 2), "unit": unit,
                           "min": rr["min"] if rr else None, "max": rr["max"] if rr else None,
                           "status": _verdict(v, rr["min"] if rr else None, rr["max"] if rr else None)})
    return {"batch_id": batch_id, "crop": p["name"], "method": method, "checks": checks,
            "basis": "Ranges are general guidance unless you edited the profile."}
