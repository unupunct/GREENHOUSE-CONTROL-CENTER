"""2D greenhouse layout (designer): storage, validation, PDF export.

Coordinates are metres from the top-left corner of the drawing. The longer side of
the greenhouse is drawn horizontally (x), the shorter vertically (y). ``x, y, w, h`` describe the item
unrotated; with rotation 90 it is drawn about the same centre with w and h swapped.
"""

from __future__ import annotations

import io
import json
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.models import Actuator, AppSetting, Sensor, Tank, Window, Zone
from app.services.greenhouse_config import load_config

router = APIRouter(prefix="/api/layout")
KEY = "layout"

LAYERS = [("structure", "Structure"), ("climate", "Climate"), ("soil_moisture", "Soil moisture"), ("irrigation", "Irrigation"),
          ("lighting", "Lighting"), ("electrical", "Electrical"), ("equipment", "Equipment")]

TYPES: dict[str, dict] = {
    "bed_soil": {"label": "Soil bed", "layer": "soil_moisture", "color": "#b08b5c", "w": 1.2, "h": 8.0},
    "bed_hydro": {"label": "Hydroponic bed", "layer": "irrigation", "color": "#7ec8e3", "w": 1.2, "h": 8.0},
    "walkway": {"label": "Walkway", "layer": "structure", "color": "#d9d9d9", "w": 1.0, "h": 10.0},
    "door": {"label": "Door", "layer": "structure", "color": "#8a6d3b", "w": 1.2, "h": 0.3},
    "tank": {"label": "Water tank", "layer": "irrigation", "color": "#4a90d9", "w": 1.5, "h": 1.5},
    "pipe": {"label": "Irrigation pipe", "layer": "irrigation", "color": "#1f5fa8", "w": 6.0, "h": 0.12},
    "valve": {"label": "Valve", "layer": "irrigation", "color": "#1f5fa8", "w": 0.3, "h": 0.3},
    "drain": {"label": "Drain", "layer": "irrigation", "color": "#555555", "w": 0.4, "h": 0.4},
    "sensor_climate": {"label": "Climate sensor", "layer": "climate", "color": "#e67e22", "w": 0.35, "h": 0.35},
    "sensor_soil": {"label": "Soil sensor", "layer": "soil_moisture", "color": "#a0522d", "w": 0.35, "h": 0.35},
    "fan": {"label": "Fan", "layer": "equipment", "color": "#7f8c8d", "w": 0.8, "h": 0.8},
    "vent": {"label": "Vent opening", "layer": "equipment", "color": "#95c11f", "w": 3.0, "h": 0.25},
    "heater": {"label": "Heater", "layer": "equipment", "color": "#d9534f", "w": 1.0, "h": 0.6},
    "light": {"label": "Grow light", "layer": "lighting", "color": "#f1c40f", "w": 1.2, "h": 0.3},
    "cabinet": {"label": "Control cabinet", "layer": "electrical", "color": "#34495e", "w": 0.6, "h": 0.4},
    "cable": {"label": "Cable route", "layer": "electrical", "color": "#2c3e50", "w": 6.0, "h": 0.08},
    "other": {"label": "Other", "layer": "equipment", "color": "#bbbbbb", "w": 0.6, "h": 0.6},
}
LINKS = {"sensor": Sensor, "actuator": Actuator, "window": Window, "zone": Zone, "tank": Tank}


class Link(BaseModel):
    kind: Literal["sensor", "actuator", "window", "zone", "tank"]
    id: str


class Item(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    type: str
    x: float = Field(ge=-1000, le=1000)
    y: float = Field(ge=-1000, le=1000)
    w: float = Field(gt=0, le=1000)
    h: float = Field(gt=0, le=1000)
    rotation: Literal[0, 90] = 0
    label: str = Field("", max_length=60)
    link: Link | None = None
    layer: str | None = None


class LayoutIn(BaseModel):
    items: list[Item] = Field(max_length=500)
    grid_m: float = Field(0.5, gt=0, le=5)


def extent(it: dict) -> tuple[float, float, float, float]:
    """Drawn rectangle (x, y, w, h) after rotation."""
    if it.get("rotation") == 90:
        cx, cy = it["x"] + it["w"] / 2, it["y"] + it["h"] / 2
        return cx - it["h"] / 2, cy - it["w"] / 2, it["h"], it["w"]
    return it["x"], it["y"], it["w"], it["h"]


def draw_dims(length_m: float, width_m: float) -> tuple[float, float]:
    """Drawing size (horizontal, vertical): the longer side is drawn horizontally."""
    return max(length_m, width_m), min(length_m, width_m)


def _load(db) -> dict:
    with db.session() as s:
        row = s.get(AppSetting, KEY)
    return json.loads(row.value) if row else {"items": [], "grid_m": 0.5}


def _warnings(items: list[dict], length: float, width: float) -> list[str]:
    out = []
    for it in items:
        x, y, w, h = extent(it)
        if x < -1e-6 or y < -1e-6 or x + w > length + 1e-6 or y + h > width + 1e-6:
            out.append(f"'{it['label'] or it['id']}' extends outside the {length:g} x {width:g} m greenhouse")
    return out


@router.get("")
def get_layout(request: Request):
    db = request.app.state.db
    cfg = load_config(db)
    doc = _load(db)
    dw, dh = draw_dims(cfg.length_m, cfg.width_m)
    return {"length_m": cfg.length_m, "width_m": cfg.width_m, "draw_w_m": dw, "draw_h_m": dh, **doc, "layers": [{"id": i, "label": l} for i, l in LAYERS],
            "types": TYPES, "warnings": _warnings(doc["items"], dw, dh)}


@router.put("")
def put_layout(body: LayoutIn, request: Request):
    db = request.app.state.db
    cfg = load_config(db)
    ids = [i.id for i in body.items]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, "item ids must be unique")
    layer_ids = {i for i, _ in LAYERS}
    with db.session() as s:
        for it in body.items:
            if it.type not in TYPES:
                raise HTTPException(422, f"unknown item type '{it.type}'")
            if it.layer is not None and it.layer not in layer_ids:
                raise HTTPException(422, f"unknown layer '{it.layer}'")
            if it.link and s.get(LINKS[it.link.kind], it.link.id) is None:
                raise HTTPException(422, f"'{it.id}': linked {it.link.kind} '{it.link.id}' does not exist")
    doc = {"items": [i.model_dump() for i in body.items], "grid_m": body.grid_m}
    with db.session() as s:
        row = s.get(AppSetting, KEY)
        payload = json.dumps(doc)
        if row is None:
            s.add(AppSetting(key=KEY, value=payload, updated_at=int(time.time())))
        else:
            row.value, row.updated_at = payload, int(time.time())
    return {**doc, "warnings": _warnings(doc["items"], *draw_dims(cfg.length_m, cfg.width_m))}


def item_layer(it: dict) -> str:
    return it.get("layer") or TYPES.get(it["type"], TYPES["other"])["layer"]


def _readings(request: Request) -> dict[str, str]:
    db = request.app.state.db
    latest = request.app.state.ingest.latest
    with db.session() as s:
        units = {x.id: x.unit for x in s.scalars(select(Sensor))}
    return {sid: f"{lv.value:g}{(' ' + units.get(sid, '')) if units.get(sid) else ''}" for sid, lv in latest.items()}


@router.get("/export.pdf")
def export_pdf(request: Request, readings: bool = False, layers: str | None = None):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas

    db = request.app.state.db
    cfg = load_config(db)
    doc = _load(db)
    shown = set(layers.split(",")) if layers else {i for i, _ in LAYERS}
    values = _readings(request) if readings else {}
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A4))
    pw, ph = landscape(A4)
    margin = 40
    dw, dh = draw_dims(cfg.length_m, cfg.width_m)
    scale = min((pw - 2 * margin) / dw, (ph - 2 * margin - 40) / dh)
    ox, oy = margin, ph - margin - 30  # top-left of the drawing

    def px(x):
        return ox + x * scale

    def py(y):
        return oy - y * scale

    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, ph - margin + 8, f"{cfg.name}: {cfg.length_m:g} x {cfg.width_m:g} m ({cfg.area_m2:g} m2)")
    c.setStrokeColor(colors.black)
    c.setLineWidth(1.5)
    c.rect(px(0), py(dh), dw * scale, dh * scale)
    c.setFont("Helvetica", 7)
    for it in doc["items"]:
        if item_layer(it) not in shown:
            continue
        x, y, w, h = extent(it)
        col = TYPES.get(it["type"], TYPES["other"])["color"]
        c.setFillColor(colors.HexColor(col))
        c.setStrokeColor(colors.HexColor("#333333"))
        c.setLineWidth(0.4)
        c.rect(px(x), py(y + h), w * scale, h * scale, fill=1, stroke=1)
        text = it["label"] or TYPES.get(it["type"], TYPES["other"])["label"]
        if it.get("link") and it["link"]["kind"] == "sensor" and it["link"]["id"] in values:
            text += f" {values[it['link']['id']]}"
        c.setFillColor(colors.black)
        c.drawString(px(x) + 2, py(y + h / 2) - 2, text.encode("latin-1", "replace").decode("latin-1")[:40])
    c.setFont("Helvetica", 7)
    c.drawString(margin, margin - 10, "Layers: " + ", ".join(l for i, l in LAYERS if i in shown) +
                 ("  |  readings shown are live values at export time" if readings else ""))
    c.showPage()
    c.save()
    return Response(buf.getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="greenhouse-layout.pdf"'})

