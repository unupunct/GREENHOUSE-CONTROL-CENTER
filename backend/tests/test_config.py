def test_default_config_matches_owner_spec(client):
    cfg = client.get("/api/config").json()
    assert cfg["length_m"] == 10 and cfg["width_m"] == 20
    assert cfg["area_m2"] == 200
    assert sorted(cfg["growing_methods"]) == ["hydroponic", "soil"]
    assert cfg["automation_level"] == "full"
    assert cfg["currency"] == "RON" and cfg["country"] == "Romania"
    # Unstated facts must not be assumed.
    assert cfg["height_m"] is None and cfg["volume_m3"] is None
    assert cfg["orientation"] is None and cfg["water_pressure_bar"] is None


def test_engineering_inputs_missing_then_provided(client):
    r = client.get("/api/config/engineering-inputs").json()
    assert r["missing"] == len(r["items"]) > 0
    cfg = client.get("/api/config").json()
    cfg["height_m"] = 3.5
    updated = client.put("/api/config", json=cfg).json()
    assert updated["volume_m3"] == 700.0
    r2 = client.get("/api/config/engineering-inputs").json()
    assert r2["missing"] == r["missing"] - 1


def test_config_persists_and_validates(client):
    cfg = client.get("/api/config").json()
    cfg["length_m"] = 12
    assert client.put("/api/config", json=cfg).json()["area_m2"] == 240
    assert client.get("/api/config").json()["length_m"] == 12
    bad = {**cfg, "length_m": -1}
    assert client.put("/api/config", json=bad).status_code == 422
    assert client.put("/api/config", json={**cfg, "growing_methods": []}).status_code == 422
