"""Shopping list assembly: BOM lines + offers + purchased flags + budget."""

from __future__ import annotations

import json
import time

from sqlalchemy import select

from app.core.db import Database
from app.core.models import AppSetting, Offer, Purchase
from app.planner import suppliers
from app.planner.catalog import SUBSYSTEMS, TIER_ORDER, build_bom, filter_lines
from app.planner.options import PlannerOptions
from app.services.greenhouse_config import GreenhouseConfig

OPTIONS_KEY = "planner"


def load_options(db: Database) -> PlannerOptions:
    with db.session() as s:
        row = s.get(AppSetting, OPTIONS_KEY)
        return PlannerOptions.model_validate(json.loads(row.value)) if row else PlannerOptions()


def save_options(db: Database, o: PlannerOptions) -> None:
    with db.session() as s:
        row = s.get(AppSetting, OPTIONS_KEY)
        payload = o.model_dump_json()
        if row is None:
            s.add(AppSetting(key=OPTIONS_KEY, value=payload, updated_at=int(time.time())))
        else:
            row.value, row.updated_at = payload, int(time.time())


def seed_offers(db: Database) -> None:
    with db.session() as s:
        if s.get(AppSetting, "offers_seeded"):
            return
        for o in suppliers.SEED_OFFERS:
            d = dict(o)
            d["checked_at"] = d.pop("checked_ts")
            s.add(Offer(**d))
        s.add(AppSetting(key="offers_seeded", value="1", updated_at=int(time.time())))


def _gross(offer: Offer, vat: float) -> float:
    return offer.price_ron if offer.includes_vat else offer.price_ron * (1 + vat)


def _offer_dict(o: Offer, vat: float) -> dict:
    return {"id": o.id, "supplier_id": o.supplier_id, "product_name": o.product_name,
            "manufacturer": o.manufacturer, "model": o.model, "price_ron": o.price_ron,
            "includes_vat": o.includes_vat, "gross_price_ron": round(_gross(o, vat), 2), "url": o.url,
            "availability": o.availability, "delivery": o.delivery, "status": o.status,
            "checked_at": o.checked_at, "note": o.note}


def _best(offers: list[Offer], vat: float) -> Offer | None:
    if not offers:
        return None
    rank = {"verified": 0, "user_estimate": 1}
    return min(offers, key=lambda o: (rank.get(o.status, 2), _gross(o, vat)))


def compute(db: Database, cfg: GreenhouseConfig, o: PlannerOptions, tier: str | None = None,
            include_optional: bool = True) -> dict:
    tier = tier or o.tier
    vat = o.vat_rate
    bom = build_bom(cfg, o)
    with db.session() as s:
        offers = s.scalars(select(Offer)).all()
        purchased = {p.item_id: p.purchased for p in s.scalars(select(Purchase))}
    by_item: dict[str, list[Offer]] = {}
    for off in offers:
        by_item.setdefault(off.item_id, []).append(off)

    def lines_for(t: str) -> list[dict]:
        out = []
        for ln in filter_lines(bom, t, include_optional):
            offs = by_item.get(ln.id, [])
            best = _best(offs, vat)
            unit = round(_gross(best, vat), 2) if best else None
            out.append({**ln.dict(),
                        "offers": [_offer_dict(x, vat) for x in offs],
                        "best_offer_id": best.id if best else None,
                        "unit_price_ron": unit,
                        "price_status": best.status if best else "none",
                        "total_ron": round(unit * ln.qty, 2) if unit is not None and ln.qty else None,
                        "purchased": purchased.get(ln.id, False)})
        return out

    lines = lines_for(tier)
    budget = _budget(lines)
    tiers = {t: _budget(lines_for(t))["grand_total_ron"] for t in TIER_ORDER}
    return {"tier": tier, "vat_rate": vat, "currency": "RON", "lines": lines, "budget": budget,
            "tier_totals_ron": tiers,
            "supplier_comparison": _supplier_comparison(lines, offers, vat),
            "label": ("Totals include ONLY lines that have a supplier price (verified or your own "
                      "estimate). Unpriced lines are not estimated by the application.")}


def _budget(lines: list[dict]) -> dict:
    by_sub = {s: {"priced_total_ron": 0.0, "lines": 0, "priced_lines": 0, "needs_input_lines": 0}
              for s in SUBSYSTEMS}
    verified = estimate = 0.0
    for ln in lines:
        b = by_sub[ln["subsystem"]]
        b["lines"] += 1
        if ln["qty"] is None:
            b["needs_input_lines"] += 1
        if ln["total_ron"] is not None:
            b["priced_lines"] += 1
            b["priced_total_ron"] = round(b["priced_total_ron"] + ln["total_ron"], 2)
            if ln["price_status"] == "verified":
                verified += ln["total_ron"]
            else:
                estimate += ln["total_ron"]
    n = len(lines)
    priced = sum(b["priced_lines"] for b in by_sub.values())
    return {"by_subsystem": {k: v for k, v in by_sub.items() if v["lines"]},
            "grand_total_ron": round(verified + estimate, 2),
            "of_which_verified_ron": round(verified, 2), "of_which_user_estimate_ron": round(estimate, 2),
            "lines": n, "priced_lines": priced, "unpriced_lines": n - priced,
            "needs_input_lines": sum(b["needs_input_lines"] for b in by_sub.values())}


def _supplier_comparison(lines: list[dict], offers: list[Offer], vat: float) -> list[dict]:
    line_by_id = {ln["id"]: ln for ln in lines}
    names = {s["id"]: s["name"] for s in suppliers.SUPPLIERS}
    out: dict[str, dict] = {}
    for off in offers:
        ln = line_by_id.get(off.item_id)
        if ln is None or not ln["qty"]:
            continue
        d = out.setdefault(off.supplier_id, {"supplier_id": off.supplier_id,
                                             "supplier": names.get(off.supplier_id, off.supplier_id),
                                             "items_covered": 0, "total_ron": 0.0})
        d["items_covered"] += 1
        d["total_ron"] = round(d["total_ron"] + _gross(off, vat) * ln["qty"], 2)
    for d in out.values():
        d["coverage_pct"] = round(100 * d["items_covered"] / max(1, len(lines)), 1)
    return sorted(out.values(), key=lambda d: -d["items_covered"])
