import csv
import io
import time
from datetime import date

import pytest

from app.analytics import stats
from app.core.models import Alert, IrrigationRun, Measurement


def ts(y, mo, d, h=0, mi=0, s=0):
    return int(time.mktime((y, mo, d, h, mi, s, 0, 0, -1)))


def put(client, sid, points):
    with client.app.state.db.session() as s:
        s.add_all(Measurement(sensor_id=sid, ts=t, value=v) for t, v in points)


def day_points(y, mo, d, value, start_h=0, end_h=24, step=60):
    return [(ts(y, mo, d, 0, 0) + k, value) for k in range(start_h * 3600, end_h * 3600, step)]


# ------------------------------------------------------------------ pure

def test_integrate_by_day_full_day_and_gaps():
    ser = {t: 1000.0 for t, _ in day_points(2026, 2, 2, 1000)}
    r = stats.integrate_by_day(ser)["2026-02-02"]
    assert r["integral"] / 1e6 == pytest.approx(86.4 - 0.06, abs=0.01)         # 1000 umol/m2/s for ~24 h
    gap = {ts(2026, 2, 2, 8): 500.0, ts(2026, 2, 2, 9): 500.0}                 # 1 h gap > cap: not integrated
    assert stats.integrate_by_day(gap) == {}
    split = {ts(2026, 2, 2, 23, 59): 100.0, ts(2026, 2, 3, 0, 0): 100.0}
    assert set(stats.integrate_by_day(split)) == {"2026-02-02"}


def test_band_share_summary_and_condensation():
    ser = {1: 0.5, 2: 1.0, 3: 1.5, 4: 2.0}
    b = stats.band_share(ser, 0.8, 1.2)
    assert b == {"in_band_pct": 25.0, "below_pct": 25.0, "above_pct": 50.0, "n": 4}
    assert stats.band_share({}, 1, 2) is None and stats.summary([]) is None
    assert stats.summary([1, 2, 3]) == {"n": 3, "min": 1, "avg": 2, "max": 3}
    # warm humid air vs cold outdoor air: dew point above outdoor temperature
    c = stats.condensation_indicator({1: 25.0, 2: 25.0}, {1: 90.0, 2: 30.0}, {1: 10.0, 2: 10.0})
    assert c["dew_point_above_outdoor_pct"] == 50.0 and "Indicator only" in c["caveat"]
    assert stats.condensation_indicator({1: 20.0}, {}, {1: 1.0}) is None


def test_period_bounds():
    assert stats.period_bounds("day", date(2026, 2, 2)) == (date(2026, 2, 2), date(2026, 2, 3))
    assert stats.period_bounds("week", date(2026, 2, 4)) == (date(2026, 2, 2), date(2026, 2, 9))   # Mon-Sun
    assert stats.period_bounds("month", date(2026, 2, 10)) == (date(2026, 2, 1), date(2026, 3, 1))
    assert stats.period_bounds("month", date(2026, 12, 31)) == (date(2026, 12, 1), date(2027, 1, 1))
    with pytest.raises(ValueError):
        stats.period_bounds("year", date(2026, 1, 1))


# ------------------------------------------------------------------- API

def test_dli_complete_vs_incomplete_days_and_crop_target(client):
    put(client, "gh_par_1", day_points(2026, 2, 2, 400.0))                       # complete day: ~34.5 mol
    put(client, "gh_par_1", day_points(2026, 2, 3, 500.0, start_h=6, end_h=18))   # half a day: incomplete
    r = client.get("/api/analytics/dli", params={"days": 3650, "crop_id": "tomato"}).json()
    d = {x["date"]: x for x in r["days"]}
    assert d["2026-02-02"]["dli_mol_m2"] == pytest.approx(34.5, abs=0.1) and d["2026-02-02"]["complete"]
    assert d["2026-02-02"]["status"] == "high"                                    # tomato target is 20-30
    assert d["2026-02-03"]["dli_mol_m2"] == pytest.approx(21.6, abs=0.1) and not d["2026-02-03"]["complete"]
    assert d["2026-02-03"]["status"] is None                                      # incomplete days are not judged
    assert r["target"] == {"min": 20, "max": 30}
    assert client.get("/api/analytics/dli", params={"sensor_id": "gh_temp_1"}).status_code == 422


def test_vpd_series_and_band(client):
    now = int(time.time())
    put(client, "gh_temp_1", [(now - 600 + k * 60, 24.0) for k in range(10)])
    put(client, "gh_rh_1", [(now - 600 + k * 60, 70.0) for k in range(10)])
    r = client.get("/api/analytics/vpd", params={"hours": 1, "crop_id": "tomato"}).json()
    assert len(r["points"]) >= 8 and r["target"] == {"min": 0.8, "max": 1.2}
    assert 0.8 < r["points"][0]["value"] < 1.2 and r["in_band"]["in_band_pct"] == 100.0
    assert client.get("/api/analytics/vpd", params={"hours": 1, "crop_id": "ghost"}).status_code == 404


def _prepare_day(client):
    put(client, "gh_temp_1", day_points(2026, 2, 2, 24.0))
    put(client, "gh_rh_1", day_points(2026, 2, 2, 70.0))
    put(client, "gh_co2_1", day_points(2026, 2, 2, 600.0))
    put(client, "gh_par_1", day_points(2026, 2, 2, 300.0))
    put(client, "out_temp_1", day_points(2026, 2, 2, 10.0))
    with client.app.state.db.session() as s:
        s.add(IrrigationRun(zone_id="soil_a", source="manual", start_ts=ts(2026, 2, 2, 8), end_ts=ts(2026, 2, 2, 8, 5),
                            planned_s=300, actual_s=300, volume_l=100.0, volume_estimate_l=110.0, end_reason="completed"))
        s.add(IrrigationRun(zone_id="soil_a", source="schedule", start_ts=ts(2026, 2, 2, 18), end_ts=ts(2026, 2, 2, 18, 1),
                            planned_s=300, actual_s=60, volume_l=None, volume_estimate_l=20.0, end_reason="flow 0 is below the minimum (dry run)"))
        s.add(Alert(ts=ts(2026, 2, 2, 9), severity="warning", code="sensor_fault", subject="x", message="m"))


def test_daily_report_contents(client):
    _prepare_day(client)
    r = client.get("/api/analytics/report", params={"period": "day", "date": "2026-02-02", "crop_id": "tomato"}).json()
    c = r["climate"]
    assert c["temperature_c"]["avg"] == 24.0 and c["humidity_pct"]["max"] == 70.0 and c["co2_ppm"]["avg"] == 600.0
    assert c["outdoor_temperature_c"]["avg"] == 10.0 and 0.8 < c["vpd_kpa"]["avg"] < 1.2
    assert r["light"]["dli_by_day"][0]["dli_mol_m2"] == pytest.approx(25.9, abs=0.1)
    assert r["light"]["dli_mean_complete_days"] == pytest.approx(25.9, abs=0.1)
    assert r["irrigation"]["runs"] == 2 and r["irrigation"]["total_measured_l"] == 100.0
    z = r["irrigation"]["by_zone"]["soil_a"]
    assert z["aborted"] == 1 and z["estimated_l"] == 130.0 and "flow sensors only" in r["irrigation"]["note"]
    assert r["alerts"]["count"] == 1 and r["alerts"]["by_code"] == {"sensor_fault": 1}
    assert r["targets"]["vpd_band"]["in_band_pct"] == 100.0 and r["targets"]["crop"] == "Tomato"
    assert r["data"]["completeness_pct"] == 1.7   # 1440 samples vs one per second (test flush interval is 1 s)
    assert r["condensation"]["dew_point_above_outdoor_pct"] == 100.0           # 24 C / 70 % -> dew point ~18 C vs 10 C outdoors
    w = client.get("/api/analytics/report", params={"period": "week", "date": "2026-02-04"}).json()
    assert w["start"] == "2026-02-02" and w["end_exclusive"] == "2026-02-09" and w["climate"]["temperature_c"]["n"] == 1440
    empty = client.get("/api/analytics/report", params={"period": "day", "date": "2020-01-01"}).json()
    assert empty["climate"]["temperature_c"] is None and empty["light"]["dli_by_day"] == [] and empty["irrigation"]["runs"] == 0
    assert client.get("/api/analytics/report", params={"date": "02/11/2026"}).status_code == 422


def test_report_files(client):
    _prepare_day(client)
    q = {"period": "day", "date": "2026-02-02", "crop_id": "tomato"}
    c = client.get("/api/analytics/report.csv", params=q)
    rows = list(csv.reader(io.StringIO(c.content.decode("utf-8-sig"))))
    assert rows[0] == ["section", "metric", "key", "value"] and any(r[:3] == ["light", "dli_mol_m2", "2026-02-02"] for r in rows)
    assert any(r[0] == "irrigation" and r[2] == "measured_l" for r in rows)
    p = client.get("/api/analytics/report.pdf", params=q)
    assert p.content[:5] == b"%PDF-" and len(p.content) > 2000
    assert client.get("/api/analytics/report.doc").status_code == 422
    assert client.get("/api/analytics/report.pdf", params={"date": "2020-01-01"}).content[:5] == b"%PDF-"  # empty period still renders


def test_seasonal_comparison_and_export(client):
    put(client, "gh_temp_1", [(ts(2025, 11, 10, 12), 18.0), (ts(2025, 11, 11, 12), 20.0), (ts(2026, 2, 10, 12), 22.0), (ts(2026, 1, 5, 12), 12.0)])
    r = client.get("/api/analytics/seasonal", params={"metric": "temperature"}).json()["monthly_means"]
    assert r["2025"] == {"11": 19.0} and r["2026"] == {"01": 12.0, "02": 22.0}
    put(client, "gh_par_1", day_points(2026, 2, 2, 400.0))
    assert client.get("/api/analytics/seasonal", params={"metric": "dli"}).json()["monthly_means"]["2026"]["02"] == pytest.approx(34.5, abs=0.1)
    assert client.get("/api/analytics/seasonal", params={"metric": "wind"}).status_code == 422
    e = client.get("/api/analytics/export/measurements.csv", params={"sensor_id": "gh_temp_1", "days": 3650})
    rows = list(csv.reader(io.StringIO(e.content.decode("utf-8-sig"))))
    assert rows[0][0] == "timestamp_utc" and len(rows) == 5 and rows[1][2] == "18.0"
    assert client.get("/api/analytics/export/measurements.csv", params={"sensor_id": "nope"}).status_code == 404
