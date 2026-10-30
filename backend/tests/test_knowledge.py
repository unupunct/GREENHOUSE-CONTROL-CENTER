import time

import pytest

from app.knowledge import plants
from app.services.ingest import LatestValue


def test_builtin_profiles_complete_and_valid():
    assert {"tomato", "cucumber", "pepper", "lettuce", "spinach", "basil", "strawberry", "eggplant"} <= set(plants.PROFILES)
    for cid, p in plants.PROFILES.items():
        assert plants.validate_profile(p) == [], cid
        assert p["soil"]["ph"]["min"] < p["soil"]["ph"]["max"]
        assert p["hydroponic"]["ec_ms_cm"]["min"] < p["hydroponic"]["ec_ms_cm"]["max"]   # separate soil/hydro profiles
        assert p["water"]["l_per_m2_day"] is None and "own figure" in p["water"]["note"]  # no invented water demand
        assert p["pests"] and p["diseases"] and p["growth_stages"] and p["nutrients"]
        assert p["light"]["dli_mol_m2_day"]["max"] > p["light"]["dli_mol_m2_day"]["min"]


def test_api_marks_general_guidance(client):
    r = client.get("/api/plants").json()
    assert "NOT verified" in r["provenance"] and len(r["plants"]) >= 8
    t = client.get("/api/plants/tomato").json()
    assert "NOT verified" in t["provenance"] and t["user_changed_fields"] == []
    assert client.get("/api/plants/nope").status_code == 404


def test_override_merge_flags_and_validation(client):
    r = client.put("/api/plants/tomato/override", json={"temperature_c": {"day_max": 27}, "notes": "my cultivar"})
    assert r.status_code == 200 and "temperature_c.day_max" in r.json()["changed"]
    t = client.get("/api/plants/tomato").json()
    assert t["profile"]["temperature_c"]["day_max"] == 27 and t["profile"]["temperature_c"]["day_min"] == 21  # others kept
    assert set(t["user_changed_fields"]) == {"temperature_c.day_max", "notes"}
    assert next(p for p in client.get("/api/plants").json()["plants"] if p["id"] == "tomato")["modified"]
    # second override accumulates
    client.put("/api/plants/tomato/override", json={"vpd_kpa": {"max": 1.4}})
    assert set(client.get("/api/plants/tomato").json()["user_changed_fields"]) == {"temperature_c.day_max", "notes", "vpd_kpa.max"}
    assert client.put("/api/plants/tomato/override", json={"vpd_kpa": {"min": 5}}).status_code == 422   # min above max
    assert client.put("/api/plants/tomato/override", json={"temperature_c": {"night_min": 30}}).status_code == 422
    assert client.put("/api/plants/tomato/override", json={"bogus": 1}).status_code == 422
    assert client.put("/api/plants/nope/override", json={"notes": "x"}).status_code == 404
    assert client.delete("/api/plants/tomato/override").status_code == 200
    assert client.get("/api/plants/tomato").json()["profile"]["temperature_c"]["day_max"] == 26
    assert client.delete("/api/plants/tomato/override").status_code == 404


def test_custom_crop_lifecycle(client):
    prof = {"name": "Parsley", "category": "herb", "temperature_c": {"day_min": 15, "day_max": 22, "night_min": 8, "night_max": 14},
            "humidity_rh": {"min": 50, "max": 70}, "vpd_kpa": {"min": 0.6, "max": 1.0}, "light": {"dli_mol_m2_day": {"min": 10, "max": 17}}}
    assert client.put("/api/plants/tomato", json=prof).status_code == 409                       # built-in protected
    assert client.put("/api/plants/Bad-Id", json=prof).status_code == 422
    assert client.put("/api/plants/parsley", json={**prof, "vpd_kpa": {"min": 2, "max": 1}}).status_code == 422
    assert client.put("/api/plants/parsley", json=prof).status_code == 200
    p = client.get("/api/plants/parsley").json()
    assert p["profile"]["custom"] and p["provenance"] == "Your own profile" and p["profile"]["pests"] == []
    assert client.put("/api/crops", json={}).status_code in (404, 405)
    assert client.post("/api/crops", json={"id": "b_pars", "crop_id": "parsley", "method": "soil", "planted_on": "2026-10-01"}).status_code == 201
    assert client.delete("/api/plants/parsley").status_code == 409                               # batch uses it
    client.delete("/api/crops/b_pars")
    assert client.delete("/api/plants/parsley").status_code == 200
    assert client.delete("/api/plants/tomato").status_code == 404


def test_setpoint_suggestion_uses_profile_and_labels_assumptions(client):
    s = client.get("/api/plants/tomato/setpoints", params={"hysteresis_c": 1.5, "fan_offset_c": 3}).json()
    assert s["day_heat_on_below"] == 21 and s["day_heat_off_above"] == 22.5
    assert s["night_heat_on_below"] == 15 and s["vent_open_above"] == 26 and s["vent_close_below"] == 24.5
    assert s["fan_on_above"] == 29 and s["fan_off_below"] == 27.5
    assert "assumptions" in s["basis"]
    client.put("/api/plants/tomato/override", json={"temperature_c": {"day_min": 19}})
    assert client.get("/api/plants/tomato/setpoints").json()["day_heat_on_below"] == 19


def test_crop_batches_and_yield(client):
    base = {"id": "tom_a", "crop_id": "tomato", "label": "Bed A", "method": "soil", "area_m2": 20, "planted_on": "2026-09-01"}
    assert client.post("/api/crops", json={**base, "crop_id": "ghost"}).status_code == 422
    assert client.post("/api/crops", json={**base, "planted_on": "2026-13-45"}).status_code == 422
    assert client.post("/api/crops", json={**base, "planted_on": "yesterday"}).status_code == 422
    assert client.post("/api/crops", json=base).status_code == 201
    assert client.post("/api/crops", json=base).status_code == 409
    assert client.post("/api/crops/tom_a/harvests", json={"date": "2026-11-01", "quantity_kg": 12.5}).status_code == 201
    assert client.post("/api/crops/tom_a/harvests", json={"date": "2026-11-08", "quantity_kg": 7.5}).status_code == 201
    assert client.post("/api/crops/nope/harvests", json={"date": "2026-11-08", "quantity_kg": 1}).status_code == 404
    assert client.post("/api/crops/tom_a/harvests", json={"date": "2026-11-08", "quantity_kg": -1}).status_code == 422
    b = client.get("/api/crops").json()[0]
    assert b["harvested_kg"] == 20 and b["yield_kg_per_m2"] == 1.0
    upd = {**base, "stage": "Fruiting", "status": "harvested"}
    assert client.put("/api/crops/tom_a", json=upd).status_code == 200
    assert client.get("/api/crops").json()[0]["stage"] == "Fruiting"
    hid = client.get("/api/crops/tom_a/harvests").json()[0]["id"]
    assert client.delete(f"/api/harvests/{hid}").status_code == 200
    assert client.delete("/api/crops/tom_a").status_code == 200
    assert client.get("/api/crops").json() == []


def _feed(client, vals):
    now = int(time.time())
    for sid, v in vals.items():
        client.app.state.ingest.latest[sid] = LatestValue(v, now, v)


def test_batch_status_compares_live_readings_with_profile(client):
    client.post("/api/crops", json={"id": "tom_h", "crop_id": "tomato", "method": "hydroponic", "planted_on": "2026-10-01"})
    for sid in ("gh_temp_1", "gh_temp_2", "gh_rh_1", "gh_rh_2", "hydro_temp_1", "hydro_ph_1", "hydro_ec_1"):
        client.app.state.ingest.latest.pop(sid, None)
    r = client.get("/api/crops/tom_h/status").json()
    assert all(c["status"] == "no_data" for c in r["checks"])          # nothing measured: no verdict
    _feed(client, {"gh_temp_1": 23, "gh_temp_2": 23, "gh_rh_1": 70, "gh_rh_2": 70, "hydro_temp_1": 20, "hydro_ph_1": 7.2, "hydro_ec_1": 2.5})
    r = client.get("/api/crops/tom_h/status", params={"day_start": "00:00", "night_start": "23:59"}).json()
    by = {c["name"]: c for c in r["checks"]}
    assert by["Air temperature (day)"]["status"] == "in_range"
    assert by["Relative humidity"]["status"] == "in_range"
    assert by["Solution pH"]["status"] == "high" and by["Solution EC"]["status"] == "in_range"
    assert by["Solution temperature"]["status"] == "in_range" and by["VPD"]["status"] in ("in_range", "low", "high")
    _feed(client, {"gh_temp_1": 12, "gh_temp_2": 12})
    r = client.get("/api/crops/tom_h/status", params={"day_start": "00:00", "night_start": "23:59"}).json()
    assert {c["name"]: c for c in r["checks"]}["Air temperature (day)"]["status"] == "low"
    client.post("/api/crops", json={"id": "tom_s", "crop_id": "tomato", "method": "soil", "planted_on": "2026-10-01"})
    names = [c["name"] for c in client.get("/api/crops/tom_s/status").json()["checks"]]
    assert not any("Solution" in n for n in names)                      # soil batches are not judged on solution
    assert client.get("/api/crops/none/status").status_code == 404
    pytest.importorskip("fastapi")
