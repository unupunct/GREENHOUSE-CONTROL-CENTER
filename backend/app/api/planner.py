from __future__ import annotations

import json
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.hardware import load_buses
from app.core.models import AppSetting, Offer, Purchase, Sensor
from app.planner import export, shopping, sizing, suppliers, wiring
from app.planner.catalog import build_bom
from app.planner.options import FIELD_META, PlannerOptions
from app.services.greenhouse_config import load_config

router = APIRouter(prefix="/api")


def _db(r: Request):
    return r.app.state.db


# ---------------------------------------------------------------- planner

@router.get("/planner/options")
def get_options(request: Request):
    return {"options": shopping.load_options(_db(request)).model_dump(), "fields": FIELD_META}


@router.put("/planner/options")
def put_options(o: PlannerOptions, request: Request):
    shopping.save_options(_db(request), o)
    return o.model_dump()


def _plan(request: Request, o: PlannerOptions) -> dict:
    cfg = load_config(_db(request))
    ar = sizing.areas(cfg, o)
    st = sizing.climate_stations(cfg, o)
    items = [ln for ln in build_bom(cfg, o) if ln.qty_missing]
    needed = sorted({m for ln in items for m in ln.qty_missing})
    return {
        "greenhouse": {"length_m": cfg.length_m, "width_m": cfg.width_m, "area_m2": cfg.area_m2,
                       "height_m": cfg.height_m, "volume_m3_estimate": cfg.volume_m3,
                       "growing_methods": cfg.growing_methods},
        "areas": ar,
        "controller": sizing.pi_recommendation(),
        "climate_stations": {"count": st, "status": "estimate",
                             "basis": f"≥1 per {o.climate_station_area_m2:g} m², minimum {o.min_climate_stations} (assumptions)",
                             "positions": ("Spread across the length at canopy level, away from fans, vents and "
                                           "heaters; one near the vent side. Heights depend on the crop - decide on site.")},
        "irrigation": sizing.irrigation(cfg, o),
        "ventilation": sizing.ventilation(cfg, o),
        "lighting": sizing.lighting(cfg, o),
        "electrical": sizing.electrical(o),
        "still_needed": needed,
        "legend": {"final": "all required inputs supplied", "needs_input": "cannot be calculated yet",
                   "estimate": "planning heuristic with editable assumptions"},
    }


@router.get("/planner/plan")
def plan(request: Request):
    return _plan(request, shopping.load_options(_db(request)))


@router.post("/planner/plan")
def plan_preview(o: PlannerOptions, request: Request):
    """Compute with unsaved options (live preview in the UI)."""
    return _plan(request, o)


class CableIn(BaseModel):
    length_m: float = Field(gt=0, le=2000)
    current_a: float = Field(gt=0, le=500)
    voltage_v: float = Field(gt=0, le=1000)
    max_drop_pct: float = Field(3.0, gt=0, le=20)


@router.post("/planner/cable")
def cable(body: CableIn):
    return sizing.cable(body.length_m, body.current_a, body.voltage_v, body.max_drop_pct)


# --------------------------------------------------------------- shopping

def _shop(request: Request, tier: str | None, include_optional: bool) -> dict:
    db = _db(request)
    return shopping.compute(db, load_config(db), shopping.load_options(db), tier, include_optional)


Tier = Literal["low", "recommended", "professional"]


@router.get("/shopping")
def shopping_list(request: Request, tier: Tier | None = None, include_optional: bool = True):
    return _shop(request, tier, include_optional)


@router.get("/shopping/suppliers")
def supplier_directory():
    return {"suppliers": suppliers.SUPPLIERS, "unverified_targets": suppliers.UNVERIFIED_TARGETS,
            "note": "Listing a supplier is not a guarantee that it stocks a given item."}


class OfferIn(BaseModel):
    item_id: str
    supplier_id: str = Field(min_length=1, max_length=48)
    product_name: str = ""
    manufacturer: str = ""
    model: str = ""
    price_ron: float = Field(gt=0, le=10_000_000)
    includes_vat: bool = True
    url: str = ""
    availability: str = ""
    delivery: str = ""
    status: Literal["verified", "user_estimate"] = "user_estimate"
    note: str = ""


@router.post("/shopping/offers", status_code=201)
def add_offer(body: OfferIn, request: Request):
    cfg, o = load_config(_db(request)), shopping.load_options(_db(request))
    if body.item_id not in {ln.id for ln in build_bom(cfg, o)}:
        raise HTTPException(422, f"unknown item '{body.item_id}'")
    if body.url and not body.url.lower().startswith(("http://", "https://")):
        raise HTTPException(422, "url must start with http:// or https://")
    with _db(request).session() as s:
        off = Offer(**body.model_dump(), checked_at=int(time.time()))
        s.add(off)
        s.flush()
        return {"id": off.id}


@router.delete("/shopping/offers/{offer_id}")
def delete_offer(offer_id: int, request: Request):
    with _db(request).session() as s:
        off = s.get(Offer, offer_id)
        if off is None:
            raise HTTPException(404, "offer not found")
        s.delete(off)
    return {"ok": True}


class PurchasedIn(BaseModel):
    purchased: bool


@router.put("/shopping/purchased/{item_id}")
def set_purchased(item_id: str, body: PurchasedIn, request: Request):
    with _db(request).session() as s:
        p = s.get(Purchase, item_id)
        if p is None:
            s.add(Purchase(item_id=item_id, purchased=body.purchased, updated_at=int(time.time())))
        else:
            p.purchased, p.updated_at = body.purchased, int(time.time())
    return {"ok": True}


@router.get("/shopping/export.{fmt}")
def export_list(fmt: Literal["csv", "xlsx", "pdf"], request: Request, tier: Tier | None = None,
                include_optional: bool = True):
    data = _shop(request, tier, include_optional)
    body, mime = {"csv": (export.to_csv, "text/csv"),
                  "xlsx": (export.to_xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                  "pdf": (export.to_pdf, "application/pdf")}[fmt]
    return Response(body(data), media_type=mime,
                    headers={"Content-Disposition": f'attachment; filename="greenhouse-shopping-{data["tier"]}.{fmt}"'})


# ----------------------------------------------------------------- wiring

@router.get("/wiring/diagrams")
def diagrams(request: Request):
    db = _db(request)
    cfg, o = load_config(db), shopping.load_options(db)
    with db.session() as s:
        sensors = s.scalars(select(Sensor)).all()
    buses = [b.model_dump() for b in load_buses(db)]
    return {"architecture": wiring.architecture(cfg, o, sensors), "power": wiring.power(cfg, o),
            "rs485": wiring.rs485_topology(sensors, buses),
            "note": "Conceptual diagrams. Pin-level wiring comes from each device's datasheet."}


@router.get("/wiring/modbus")
def modbus(request: Request):
    return wiring.modbus_table(_db(request))


@router.get("/wiring/gpio")
def gpio(request: Request):
    return {"fixed": wiring.PI_FIXED_PINS, "assigned": wiring.load_gpio(_db(request)),
            "note": "Only interfaces this application uses are listed as fixed. Other GPIO "
                    "assignments are yours; none are suggested for specific devices."}


class GpioRow(BaseModel):
    bcm: int
    function: str
    device: str = ""
    note: str = ""


@router.put("/wiring/gpio")
def put_gpio(rows: list[GpioRow], request: Request):
    data = [r.model_dump() for r in rows]
    errs = wiring.validate_gpio(data)
    if errs:
        raise HTTPException(422, "; ".join(errs))
    with _db(request).session() as s:
        row = s.get(AppSetting, wiring.GPIO_KEY)
        payload = json.dumps(data)
        if row is None:
            s.add(AppSetting(key=wiring.GPIO_KEY, value=payload, updated_at=int(time.time())))
        else:
            row.value, row.updated_at = payload, int(time.time())
    return data
