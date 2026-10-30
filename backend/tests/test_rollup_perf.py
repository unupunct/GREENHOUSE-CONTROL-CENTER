import asyncio
import time

import pytest
from sqlalchemy import func, select

from app.analytics import stats
from app.core.models import Measurement, MeasurementHourly
from app.services import rollup
from app.services.ingest import LatestValue


def ts(y, mo, d, h=0, mi=0, s=0):
    return int(time.mktime((y, mo, d, h, mi, s, 0, 0, -1)))


def put(client, sid, points):
    with client.app.state.db.session() as s:
        s.add_all(Measurement(sensor_id=sid, ts=t, value=v) for t, v in points)


def hourly(client, sid=None):
    with client.app.state.db.session() as s:
        q = select(MeasurementHourly).order_by(MeasurementHourly.hour_ts)
        if sid:
            q = q.where(MeasurementHourly.sensor_id == sid)
        return [(h.sensor_id, h.hour_ts, h.n, h.vmin, h.vmax, round(h.vavg, 3)) for h in s.scalars(q)]


def test_roll_summarises_only_complete_hours_and_is_idempotent(client):
    base = ts(2026, 1, 10, 10)
    put(client, "gh_temp_1", [(base + i * 60, 20.0 + (i % 60) / 60) for i in range(150)])   # 10:00 - 12:29
    now = base + 150 * 60 + 5                                                                 # 12:35: hours 10 and 11 are complete
    assert rollup.roll(client.app.state.db, now) == 2
    rows = hourly(client, "gh_temp_1")
    assert [r[1] for r in rows] == [base, base + 3600] and rows[0][2] == 60 and rows[0][3] == 20.0 and rows[0][4] == pytest.approx(20.983, abs=0.001)
    assert rollup.roll(client.app.state.db, now) == 0                                          # nothing new
    assert rollup.rolled_until(client.app.state.db) == base + 2 * 3600
    rollup.roll(client.app.state.db, base + 4 * 3600 + 5)                                      # the third hour is complete later
    assert [r[1] for r in hourly(client, "gh_temp_1")] == [base, base + 3600, base + 7200]
    with client.app.state.db.session() as s:                                                   # never overwritten
        s.add(Measurement(sensor_id="gh_temp_1", ts=base + 30, value=999.0))
    rollup.roll(client.app.state.db, base + 10 * 3600)
    assert hourly(client, "gh_temp_1")[0][4] == pytest.approx(20.983, abs=0.001)


def test_prune_keeps_summaries_and_never_splits_an_hour(client):
    client.app.state.settings.retention_days = 90
    now = ts(2026, 6, 1, 12, 20)
    old = now - 100 * 86400
    put(client, "gh_temp_1", [(old - 7200 + i * 60, 18.0) for i in range(240)])               # four old hours
    put(client, "gh_temp_1", [(now - 3600 + i * 60, 22.0) for i in range(60)])                # recent
    n = client.app.state.ingest.prune(now)
    assert n >= 200
    with client.app.state.db.session() as db:
        oldest = db.scalar(select(func.min(Measurement.ts)).where(Measurement.sensor_id == "gh_temp_1"))
    cutoff = int((now - 90 * 86400) // 3600 * 3600)
    assert oldest >= cutoff and cutoff % 3600 == 0                                              # aligned to whole hours
    assert len([r for r in hourly(client, "gh_temp_1") if r[5] == 18.0]) >= 3                    # the pruned data lives on as hourly
    assert client.app.state.ingest.prune(now) == 0


def test_unsummarised_samples_are_never_deleted(client, monkeypatch):
    s = client.app.state.settings
    now = ts(2026, 6, 1, 12, 20)
    put(client, "gh_temp_1", [(now - 120 * 86400 + i * 60, 18.0) for i in range(60)])
    monkeypatch.setattr(rollup, "roll", lambda *a, **k: 0)                                      # summarising broken
    assert rollup.prune(client.app.state.db, s, now) == 0                                        # so nothing may be deleted
    monkeypatch.undo()
    assert rollup.prune(client.app.state.db, s, now) >= 60 and hourly(client, "gh_temp_1")


def test_old_months_survive_pruning_for_seasonal_comparison(client):
    now = ts(2026, 7, 15, 12)
    put(client, "gh_temp_1", [(ts(2025, 7, 10, 12) + i * 60, 30.0) for i in range(120)])        # a year ago
    put(client, "gh_temp_1", [(ts(2026, 7, 14, 12) + i * 60, 26.0) for i in range(120)])        # now
    client.app.state.ingest.prune(now)
    with client.app.state.db.session() as db:
        assert not db.scalar(select(func.count()).select_from(Measurement).where(Measurement.ts < ts(2026, 1, 1)))   # raw is gone
    m = stats.monthly_means(client.app.state.db, ["gh_temp_1"])
    assert m["2025"]["07"] == 30.0 and m["2026"]["07"] == 26.0                                   # but the comparison remains
    api = client.get("/api/analytics/seasonal", params={"metric": "temperature"}).json()["monthly_means"]
    assert api["2025"]["07"] == 30.0


def test_history_falls_back_to_hourly_for_old_ranges(client):
    now = int(time.time())
    base = (now - 150 * 86400) // 3600 * 3600
    put(client, "gh_temp_1", [(base + i * 60, 15.0) for i in range(180)])                        # 150 days ago
    put(client, "gh_temp_1", [(now - 600 + i * 60, 21.0) for i in range(10)])
    client.app.state.settings.retention_days = 90
    client.app.state.ingest.prune(now)
    r = client.get("/api/readings/history", params={"sensor_id": "gh_temp_1", "hours": 24 * 200, "max_points": 500}).json()["points"]
    vals = {round(p["value"]) for p in r}
    assert 15 in vals and 21 in vals and len(r) <= 500
    assert r == sorted(r, key=lambda p: p["ts"])


def test_history_is_bucketed_in_sql_and_stays_fast(client):
    now = int(time.time())
    put(client, "gh_temp_1", [(now - 30 * 86400 + i * 60, 10.0 + (i % 100) / 10) for i in range(43000)])
    t0 = time.time()
    r = client.get("/api/readings/history", params={"sensor_id": "gh_temp_1", "hours": 24 * 30, "max_points": 200}).json()["points"]
    dt = time.time() - t0
    assert 100 <= len(r) <= 260 and dt < 3.0
    assert 10 <= min(p["value"] for p in r) and max(p["value"] for p in r) <= 20
    short = client.get("/api/readings/history", params={"sensor_id": "gh_temp_1", "hours": 1}).json()["points"]
    assert len(short) <= 61


def test_series_mean_across_sensors_is_computed_in_sql(client):
    t = ts(2026, 3, 3, 12)
    put(client, "gh_temp_1", [(t + i * 60, 20.0) for i in range(5)])
    put(client, "gh_temp_2", [(t + i * 60, 24.0) for i in range(5)])
    put(client, "gh_temp_2", [(t + 600, 30.0)])
    ser = stats.series(client.app.state.db, ["gh_temp_1", "gh_temp_2"], t, t + 3600)
    assert list(ser.values())[:5] == [22.0] * 5 and ser[t + 600] == 30.0 and list(ser) == sorted(ser)
    assert stats.series(client.app.state.db, [], t, t + 1) == {}


def test_report_over_a_week_of_data_is_fast(client):
    t0 = ts(2026, 2, 2)
    for sid, v in (("gh_temp_1", 22.0), ("gh_temp_2", 23.0), ("gh_rh_1", 65.0), ("gh_rh_2", 67.0), ("gh_par_1", 300.0), ("gh_co2_1", 600.0)):
        put(client, sid, [(t0 + i * 60, v) for i in range(7 * 1440)])
    t = time.time()
    r = client.get("/api/analytics/report", params={"period": "week", "date": "2026-02-04", "crop_id": "tomato"})
    assert r.status_code == 200 and time.time() - t < 8.0
    j = r.json()
    assert j["climate"]["temperature_c"]["n"] == 7 * 1440 and j["climate"]["temperature_c"]["avg"] == 22.5
    assert len([d for d in j["light"]["dli_by_day"] if d["complete"]]) == 7


def test_deleting_a_sensor_removes_its_summaries(client):
    base = ts(2026, 1, 1, 0)
    put(client, "gh_temp_1", [(base + i * 60, 20.0) for i in range(120)])
    rollup.roll(client.app.state.db, base + 86400)
    assert hourly(client, "gh_temp_1")
    assert client.delete("/api/sensors/gh_temp_1").status_code == 200
    assert hourly(client, "gh_temp_1") == []


def test_ticks_do_not_recompute_the_commissioning_gate_every_second(client):
    eng, clim = client.app.state.engine, client.app.state.climate
    calls = {"n": 0}
    base_gate = eng.gate_fn

    def counting():
        calls["n"] += 1
        return base_gate()

    eng.gate_fn = clim.gate_fn = counting
    t = [1_800_000_000.0]
    eng.clock = clim.clock = lambda: t[0]
    eng.reload()
    clim.reload()
    for sid in ("sim_tank_level", "sim_tank_float", "sim_flow_main"):
        client.app.state.ingest.latest[sid] = LatestValue(50.0, int(t[0]), 50.0)
    client.put("/api/irrigation/settings", json={**client.get("/api/irrigation/setup").json()["settings"], "auto_enabled": True})
    client.put("/api/climate/settings", json={"auto_enabled": True, "sensor_max_age_s": 30})
    calls["n"] = 0
    for _ in range(100):
        t[0] += 1
        asyncio.run(eng.tick(t[0]))
        asyncio.run(clim.tick(t[0]))
    assert calls["n"] <= 110, calls                              # two engines x about one evaluation per 2 s (was 200)
    eng.invalidate_gate()
    n = calls["n"]
    eng.auto_allowed()
    assert calls["n"] == n + 1                                     # invalidation forces a fresh evaluation


def test_gate_change_is_seen_immediately_after_checklist_actions(client):
    eng = client.app.state.engine
    assert eng.auto_allowed()[1] in ("automatic irrigation is switched off", "commissioning checks have not all passed")
    client.put("/api/irrigation/settings", json={**client.get("/api/irrigation/setup").json()["settings"], "auto_enabled": True})
    assert "commissioning" in eng.auto_allowed()[1]
    asyncio.run(client.app.state.ingest.poll_once())
    for cid in ("sensor_communication", "modbus_communication", "database_operation", "pump_protection", "water_level_interlock", "emergency_stop", "backup_restore"):
        client.post(f"/api/safety/checks/{cid}/run")
    for cid in ("gpio_operation", "mqtt_communication", "actuator_feedback", "pump_protection", "water_level_interlock", "emergency_stop", "watchdog", "automatic_restart"):
        client.post(f"/api/safety/checks/{cid}/attest", json={"note": "tested on the bench, fine"})
    assert eng.auto_allowed() == (True, "ok")                        # no stale cached 'closed' gate
    client.delete("/api/safety/checks/watchdog")
    assert eng.auto_allowed()[0] is False
