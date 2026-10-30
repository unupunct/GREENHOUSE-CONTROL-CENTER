"""Generate docs/HARDWARE_LIST.md from the planner's bill of materials of a running server.

    python scripts/make_hardware_list.py http://127.0.0.1:8110

The list is whatever the planner computes for the greenhouse configured on that server. Prices appear only for lines that
have a recorded supplier offer; nothing is estimated.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
OUT = Path(__file__).resolve().parents[1] / "docs" / "HARDWARE_LIST.md"


def get(path: str):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read())


cfg = get("/api/config")
shop = get("/api/shopping?tier=professional&include_optional=true")
plan = get("/api/planner/plan")
tier_label = {"low": "all", "recommended": "recommended +", "professional": "professional only"}
subs: dict[str, list] = {}
for ln in shop["lines"]:
    subs.setdefault(ln["subsystem"], []).append(ln)

md = [
    "# Hardware list (200 m² greenhouse, default assumptions)",
    "",
    f"*Generated {time.strftime('%Y-%m-%d')} by `scripts/make_hardware_list.py` from the planner of a running installation "
    f"({cfg['length_m']:g} m x {cfg['width_m']:g} m = {cfg['area_m2']:g} m², soil and hydroponics). Regenerate it, or open the Shopping page, "
    "for YOUR greenhouse: quantities change with size, growing method and the inputs you give the planner.*",
    "",
    "## How to read this list",
    "",
    "- **Qty** is calculated from the planner. **?** means the quantity cannot be calculated until you supply the inputs named in the "
    "*Needs* column (for example fan airflow from the datasheet of the fan you choose). The application never guesses them.",
    "- **From tier**: *all* = part of the low-cost configuration and above; *recommended +* = recommended and professional; *professional only*.",
    "- Items are **generic requirements** (\"24 V DIN-rail supply\") unless a real product is named. No specification, price or link is "
    "invented: where a price is shown it was read from a supplier page on the date given; everything else is **no price recorded**, "
    "which means *not researched*, not *free*.",
    "- Heuristic counts (climate stations per area, probes per zone, manifold outlets) are editable assumptions: see the Planner page.",
    "- Mains-side items (breakers, RCD, contactors, earthing) are listed so you can brief an electrician; **they must be designed and "
    "installed by a qualified electrician.** Hardware protections (float switch in the pump circuit, hardware e-stop, heater over-temperature "
    "cut-out, window limit switches) are part of the list on purpose: the software is not allowed to be the only protection.",
    "",
    "Supporting facts: the planner computes a soil area of "
    f"{plan['areas']['soil_m2']:g} m² and hydroponic area of {plan['areas']['hydro_m2']:g} m² (50/50 split assumption), "
    f"{plan['climate_stations']['count']} climate stations, {plan['irrigation']['soil_zones']} soil irrigation zone(s) of at most 50 m² "
    f"and {plan['irrigation']['hydro_zones']} hydroponic zone(s). "
    "The recommended controller is *" + plan["controller"]["recommended"] + "*.",
    "",
]
for sub, lines in subs.items():
    md += [f"## {sub}", "", "| Item | Qty | From tier | Requirement / notes | Needs | Price |", "|---|---|---|---|---|---|"]
    for ln in lines:
        offer = next((o for o in ln["offers"] if o["id"] == ln["best_offer_id"]), None)
        price = (f"{ln['unit_price_ron']:.2f} RON ({'verified ' + time.strftime('%Y-%m-%d', time.localtime(offer['checked_at'])) if ln['price_status'] == 'verified' else 'your estimate'})"
                 if ln["unit_price_ron"] is not None else "no price recorded")
        spec = (ln["spec"] or "").replace("|", "/")
        alt = f" *Alternatives:* {'; '.join(ln['alternatives'])}." if ln["alternatives"] else ""
        compat = f" {ln['compat']}" if ln["compat"] else ""
        md.append(f"| {ln['name'].replace('|', '/')} | {'?' if ln['qty'] is None else ln['qty']} | {tier_label[ln['min_tier']]} | {spec}{alt}{compat} | "
                  f"{', '.join(ln['qty_missing']) if ln['qty_missing'] else ln['qty_basis']} | {price} |")
    md.append("")
b = shop["budget"]
md += ["## Totals", "",
       f"{shop['budget']['lines']} lines (professional view incl. optional). Priced lines total {b['grand_total_ron']:.2f} RON; **{b['unpriced_lines']} lines have no recorded price**, "
       f"{b['needs_input_lines']} quantities still need inputs. A complete budget cannot be stated until you research prices: see BUDGET.md.", "",
       "## What this list does not include", "",
       "Mains installation design and labour, greenhouse structure and covering, groundwater/water supply connection, heating equipment sizing "
       "(the application does not calculate a heat load), crop inputs, nutrients, running costs, shipping and duties.", ""]
OUT.write_text("\n".join(md), encoding="utf-8")
print(f"wrote {OUT} ({len(shop['lines'])} lines)")
