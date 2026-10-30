"""Aggregations over the measurement history. All calendar logic uses local time."""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, select

from app.core.db import Database
from app.core.models import Measurement, MeasurementHourly, Sensor
from app.services import climate

GAP_CAP_S = 300  # a gap longer than this between samples is not integrated (no data, not "same value")


def day_key(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def day_start_ts(d: date) -> int:
    return int(time.mktime((d.year, d.month, d.day, 0, 0, 0, 0, 0, -1)))


def sensor_ids(db: Database, zone: str, kind: str) -> list[str]:
    with db.session() as s:
        return [x.id for x in s.scalars(select(Sensor).where(Sensor.zone == zone, Sensor.kind == kind))]


def series(db: Database, ids: list[str], since: int, until: int) -> dict[int, float]:
    """Mean across the given sensors at each stored timestamp."""
    if not ids:
        return {}
    with db.session() as s:  # the mean across sensors is computed by SQLite, not in Python
        rows = s.execute(select(Measurement.ts, func.avg(Measurement.value)).where(
            Measurement.sensor_id.in_(ids), Measurement.ts >= since, Measurement.ts < until)
            .group_by(Measurement.ts).order_by(Measurement.ts)).all()
    return {ts: v for ts, v in rows}


def summary(values: list[float]) -> dict | None:
    if not values:
        return None
    return {"n": len(values), "min": round(min(values), 3), "avg": round(sum(values) / len(values), 3),
            "max": round(max(values), 3)}


def daily_summary(ser: dict[int, float]) -> list[dict]:
    by: dict[str, list[float]] = defaultdict(list)
    for ts, v in ser.items():
        by[day_key(ts)].append(v)
    return [{"date": d, **summary(v)} for d, v in sorted(by.items())]  # type: ignore[arg-type]


def integrate_by_day(ser: dict[int, float], cap_s: int = GAP_CAP_S) -> dict[str, dict]:
    """Left-Riemann integral of value (per second) over each local day.

    Returns {date: {"integral": value*seconds, "covered_s": seconds with data}}.
    For PAR in umol/m2/s, mol/m2 = integral / 1e6.
    """
    out: dict[str, dict] = {}
    items = list(ser.items())
    for (t0, v0), (t1, _v1) in zip(items, items[1:], strict=False):
        gap = t1 - t0
        if gap <= 0 or gap > cap_s:
            continue
        d = out.setdefault(day_key(t0), {"integral": 0.0, "covered_s": 0.0})
        d["integral"] += v0 * gap
        d["covered_s"] += gap
    return out


def dli_by_day(db: Database, ids: list[str], since: int, until: int) -> list[dict]:
    res = integrate_by_day(series(db, ids, since, until))
    return [{"date": d, "dli_mol_m2": round(v["integral"] / 1e6, 3),
             "coverage_pct": round(min(100.0, v["covered_s"] / 86400 * 100), 1),
             "complete": v["covered_s"] >= 0.9 * 86400} for d, v in sorted(res.items())]


def vpd_series(temp: dict[int, float], rh: dict[int, float]) -> dict[int, float]:
    return {ts: climate.vpd_kpa(temp[ts], rh[ts]) for ts in temp if ts in rh}


def band_share(ser: dict[int, float], lo: float | None, hi: float | None) -> dict | None:
    """Share of samples inside / below / above a target band."""
    if not ser:
        return None
    n = len(ser)
    low = sum(1 for v in ser.values() if lo is not None and v < lo)
    high = sum(1 for v in ser.values() if hi is not None and v > hi)
    return {"in_band_pct": round(100 * (n - low - high) / n, 1), "below_pct": round(100 * low / n, 1),
            "above_pct": round(100 * high / n, 1), "n": n}


def condensation_indicator(gh_t: dict[int, float], gh_rh: dict[int, float], out_t: dict[int, float]) -> dict | None:
    """INDICATOR ONLY: share of samples where the greenhouse dew point is at or above the OUTDOOR
    temperature. The inner surface of the covering is usually between indoor and outdoor
    temperature, so this over-states risk for good coverings and under-states it for none."""
    common = [ts for ts in gh_t if ts in gh_rh and ts in out_t]
    if not common:
        return None
    hits = sum(1 for ts in common if climate.dew_point_c(gh_t[ts], gh_rh[ts]) >= out_t[ts])
    return {"samples": len(common), "dew_point_above_outdoor_pct": round(100 * hits / len(common), 1),
            "caveat": "Indicator only: uses outdoor temperature as a stand-in for the cold covering surface."}


def monthly_means(db: Database, ids: list[str]) -> dict[str, dict[str, float]]:
    """{year: {month: mean}} of the per-timestamp mean across sensors."""
    if not ids:
        return {}
    from app.services.rollup import rolled_until
    until = rolled_until(db)
    tot: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0.0])  # (year, month) -> [sum, n]

    def add(hour_ts: int, avg: float, n: int) -> None:
        lt = time.localtime(hour_ts)
        t = tot[(str(lt.tm_year), f"{lt.tm_mon:02d}")]
        t[0] += avg * n
        t[1] += n

    with db.session() as s:
        # summarised hours (long-lived) ...
        for hour_ts, avg, n in s.execute(select(MeasurementHourly.hour_ts, MeasurementHourly.vavg, MeasurementHourly.n).where(
                MeasurementHourly.sensor_id.in_(ids), MeasurementHourly.hour_ts < until)):
            add(hour_ts, avg, n)
        # ... plus raw samples not yet summarised, aggregated per sensor-hour by SQLite
        for hour, avg, n in s.execute(select(Measurement.ts.op("/")(3600), func.avg(Measurement.value), func.count()).where(
                Measurement.sensor_id.in_(ids), Measurement.ts >= until).group_by(Measurement.sensor_id, Measurement.ts.op("/")(3600))):
            add(int(hour) * 3600, avg, n)
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for (y, m), (sm, n) in sorted(tot.items()):
        out[y][m] = round(sm / n, 3)
    return dict(out)


def period_bounds(period: str, anchor: date) -> tuple[date, date]:
    """[start, end) dates for the day / ISO week (Mon-Sun) / calendar month containing ``anchor``."""
    if period == "day":
        return anchor, anchor + timedelta(days=1)
    if period == "week":
        start = anchor - timedelta(days=anchor.weekday())
        return start, start + timedelta(days=7)
    if period == "month":
        start = anchor.replace(day=1)
        nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        return start, nxt
    raise ValueError(period)
