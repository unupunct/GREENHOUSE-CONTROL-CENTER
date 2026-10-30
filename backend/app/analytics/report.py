"""Daily / weekly / monthly reports (JSON, CSV, PDF)."""

from __future__ import annotations

import csv
import io
import time
from collections import Counter
from datetime import date

from sqlalchemy import select

from app.analytics import stats
from app.core.db import Database
from app.core.models import Alert, DailyStat, Event, IrrigationRun


def build(db: Database, period: str, anchor: date, profile: dict | None, flush_interval_s: float) -> dict:
    d0, d1 = stats.period_bounds(period, anchor)
    t0, t1 = stats.day_start_ts(d0), stats.day_start_ts(d1)
    g = lambda kind, zone="greenhouse": stats.series(db, stats.sensor_ids(db, zone, kind), t0, t1)  # noqa: E731
    temp, rh, co2 = g("temperature"), g("humidity"), g("co2")
    out_t = g("temperature", "outdoor")
    vpd = stats.vpd_series(temp, rh)
    dli = stats.dli_by_day(db, stats.sensor_ids(db, "greenhouse", "par"), t0, t1)
    expected = max(1, int((t1 - t0) / max(flush_interval_s, 1)))
    rep: dict = {
        "period": period, "start": d0.isoformat(), "end_exclusive": d1.isoformat(),
        "generated_at": int(time.time()),
        "climate": {
            "temperature_c": stats.summary(list(temp.values())), "humidity_pct": stats.summary(list(rh.values())),
            "vpd_kpa": stats.summary(list(vpd.values())), "co2_ppm": stats.summary(list(co2.values())),
            "outdoor_temperature_c": stats.summary(list(out_t.values())),
            "daily_temperature_c": stats.daily_summary(temp),
        },
        "light": {"dli_by_day": dli,
                  "dli_mean_complete_days": (round(sum(x["dli_mol_m2"] for x in dli if x["complete"]) /
                                                   max(1, sum(1 for x in dli if x["complete"])), 3)
                                             if any(x["complete"] for x in dli) else None),
                  "note": "DLI integrates the PAR sensor; days with under 90% coverage are marked incomplete."},
        "data": {"temperature_samples": len(temp), "expected_samples_approx": expected,
                 "completeness_pct": round(min(100.0, 100 * len(temp) / expected), 1)},
        "condensation": stats.condensation_indicator(temp, rh, out_t),
    }
    if profile:
        v, t = profile["vpd_kpa"], profile["temperature_c"]
        rep["targets"] = {"crop": profile["name"], "basis": "general guidance unless edited",
                          "vpd_band": stats.band_share(vpd, v["min"], v["max"]),
                          "humidity_band": stats.band_share(rh, profile["humidity_rh"]["min"], profile["humidity_rh"]["max"]),
                          "temperature_range_c": {"night_min": t["night_min"], "day_max": t["day_max"]},
                          "temperature_band_note": "Temperature is judged day/night in the live status view; "
                                                   "here only the extreme limits (night min, day max) are used.",
                          "temperature_band": stats.band_share(temp, t["night_min"], t["day_max"])}
    with db.session() as s:
        runs = s.scalars(select(IrrigationRun).where(IrrigationRun.start_ts >= t0, IrrigationRun.start_ts < t1)).all()
        days = [x.isoformat() for x in (d0.fromordinal(o) for o in range(d0.toordinal(), d1.toordinal()))]
        dstats = s.scalars(select(DailyStat).where(DailyStat.date.in_(days))).all()
        alerts = s.scalars(select(Alert).where(Alert.ts >= t0, Alert.ts < t1)).all()
        errors = len(s.scalars(select(Event.id).where(Event.ts >= t0, Event.ts < t1, Event.level == "error")).all())
    zones: dict[str, dict] = {}
    for r in runs:
        z = zones.setdefault(r.zone_id, {"runs": 0, "seconds": 0, "measured_l": 0.0, "estimated_l": 0.0, "aborted": 0})
        z["runs"] += 1
        z["seconds"] += r.actual_s or 0
        z["measured_l"] += r.volume_l or 0.0
        z["estimated_l"] += r.volume_estimate_l or 0.0
        z["aborted"] += 1 if r.end_reason not in (None, "completed", "moisture_reached", "stopped_by_user") else 0
    rep["irrigation"] = {"runs": len(runs), "by_zone": {k: {**v, "measured_l": round(v["measured_l"], 2),
                                                             "estimated_l": round(v["estimated_l"], 2)} for k, v in zones.items()},
                         "total_measured_l": round(sum(z["measured_l"] for z in zones.values()), 2),
                         "total_estimated_l": round(sum(z["estimated_l"] for z in zones.values()), 2),
                         "note": "Measured litres come from flow sensors only; estimated = your expected flow x run time."}
    rep["lighting"] = {"energy_kwh": round(sum(x.value for x in dstats if x.key == "light_kwh"), 3),
                       "lights_on_h": round(sum(x.value for x in dstats if x.key == "light_on_s") / 3600, 2),
                       "note": "Energy needs a power sensor on a lighting program; other loads are not metered."}
    rep["alerts"] = {"count": len(alerts), "by_code": dict(Counter(a.code for a in alerts)), "error_events": errors}
    return rep


def to_csv(rep: dict) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["section", "metric", "key", "value"])
    w.writerow(["report", "period", "", f"{rep['period']} {rep['start']} to {rep['end_exclusive']} (end exclusive)"])
    for name, s in rep["climate"].items():
        if isinstance(s, dict):
            for k, v in s.items():
                w.writerow(["climate", name, k, v])
    for d in rep["climate"]["daily_temperature_c"]:
        w.writerow(["climate", "daily_temperature_c", d["date"], f"min {d['min']} avg {d['avg']} max {d['max']}"])
    for d in rep["light"]["dli_by_day"]:
        w.writerow(["light", "dli_mol_m2", d["date"], d["dli_mol_m2"]])
        w.writerow(["light", "dli_coverage_pct", d["date"], d["coverage_pct"]])
    for z, v in rep["irrigation"]["by_zone"].items():
        for k, val in v.items():
            w.writerow(["irrigation", z, k, val])
    w.writerow(["irrigation", "total", "measured_l", rep["irrigation"]["total_measured_l"]])
    w.writerow(["lighting", "energy_kwh", "", rep["lighting"]["energy_kwh"]])
    w.writerow(["lighting", "lights_on_h", "", rep["lighting"]["lights_on_h"]])
    w.writerow(["alerts", "count", "", rep["alerts"]["count"]])
    for code, n in rep["alerts"]["by_code"].items():
        w.writerow(["alerts", "by_code", code, n])
    if rep.get("targets"):
        for band in ("vpd_band", "humidity_band", "temperature_band"):
            for k, v in (rep["targets"].get(band) or {}).items():
                w.writerow(["targets", band, k, v])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def _p(text) -> str:
    s = str(text).replace("≥", ">=").replace("≤", "<=").replace("→", "->").replace("₂", "2").replace("–", "-")
    return s.encode("latin-1", "replace").decode("latin-1")


def to_pdf(rep: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    st = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    story = [Paragraph(_p(f"Greenhouse {rep['period']} report: {rep['start']} to {rep['end_exclusive']} (end exclusive)"), st["Title"]),
             Paragraph(_p(f"Data completeness about {rep['data']['completeness_pct']}% "
                          f"({rep['data']['temperature_samples']} temperature samples)."), st["BodyText"]), Spacer(1, 8)]

    def table(rows, widths=None):
        t = Table([[_p(c) for c in r] for r in rows], colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2e8b57")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                               ("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 8)]))
        story.extend([t, Spacer(1, 10)])

    story.append(Paragraph("Climate", st["Heading2"]))
    rows = [["Quantity", "Min", "Average", "Max", "Samples"]]
    for label, key in (("Temperature C", "temperature_c"), ("Humidity %", "humidity_pct"), ("VPD kPa", "vpd_kpa"),
                       ("CO2 ppm", "co2_ppm"), ("Outdoor C", "outdoor_temperature_c")):
        s = rep["climate"][key]
        rows.append([label] + ([s["min"], s["avg"], s["max"], s["n"]] if s else ["-", "-", "-", 0]))
    table(rows)
    story.append(Paragraph("Light (DLI)", st["Heading2"]))
    table([["Date", "DLI mol/m2/day", "Coverage %", "Complete"]] +
          [[d["date"], d["dli_mol_m2"], d["coverage_pct"], "yes" if d["complete"] else "no"] for d in rep["light"]["dli_by_day"]]
          if rep["light"]["dli_by_day"] else [["No PAR data in this period"]])
    if rep.get("targets"):
        tg = rep["targets"]
        story.append(Paragraph(_p(f"Time within {tg['crop']} targets (general guidance unless edited)"), st["Heading2"]))
        rows = [["Band", "In band %", "Below %", "Above %"]]
        for label, key in (("VPD", "vpd_band"), ("Humidity", "humidity_band"), ("Temperature (extreme limits)", "temperature_band")):
            b = tg.get(key)
            rows.append([label] + ([b["in_band_pct"], b["below_pct"], b["above_pct"]] if b else ["-", "-", "-"]))
        table(rows)
    story.append(Paragraph("Irrigation and lighting", st["Heading2"]))
    ir = rep["irrigation"]
    rows = [["Zone", "Runs", "Seconds", "Measured L", "Estimated L", "Aborted"]]
    rows += [[z, v["runs"], v["seconds"], v["measured_l"], v["estimated_l"], v["aborted"]] for z, v in ir["by_zone"].items()]
    table(rows if len(rows) > 1 else [["No irrigation runs in this period"]])
    story.append(Paragraph(_p(f"Lighting energy {rep['lighting']['energy_kwh']} kWh, lights on {rep['lighting']['lights_on_h']} h. "
                              f"Alerts: {rep['alerts']['count']}."), st["BodyText"]))
    if rep.get("condensation"):
        story.append(Paragraph(_p(f"Condensation indicator: {rep['condensation']['dew_point_above_outdoor_pct']}% of samples "
                                  f"had a dew point above the outdoor temperature. {rep['condensation']['caveat']}"), st["BodyText"]))
    doc.build(story)
    return buf.getvalue()

