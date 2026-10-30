import pytest

from app.api import layout
from app.services.ingest import LatestValue


def item(id_="b1", type_="bed_soil", x=1.0, y=1.0, w=1.2, h=8.0, **kw):
    return {"id": id_, "type": type_, "x": x, "y": y, "w": w, "h": h, **kw}


def test_extent_rotation():
    assert layout.extent({"x": 2, "y": 1, "w": 4, "h": 2, "rotation": 0}) == (2, 1, 4, 2)
    x, y, w, h = layout.extent({"x": 2, "y": 1, "w": 4, "h": 2, "rotation": 90})   # same centre (4, 2), w/h swapped
    assert (x, y, w, h) == (3, 0, 2, 4)


def test_layers_types_and_default(client):
    d = client.get("/api/layout").json()
    assert d["items"] == [] and d["length_m"] == 10 and d["width_m"] == 20
    assert (d["draw_w_m"], d["draw_h_m"]) == (20, 10)   # long side drawn horizontally
    assert [l["id"] for l in d["layers"]] == ["structure", "climate", "soil_moisture", "irrigation", "lighting", "electrical", "equipment"]
    assert {"bed_soil", "bed_hydro", "walkway", "tank", "pipe", "fan", "vent", "sensor_climate", "light", "heater", "drain", "cabinet"} <= set(d["types"])
    assert layout.item_layer({"type": "light"}) == "lighting"
    assert layout.item_layer({"type": "light", "layer": "electrical"}) == "electrical"


def test_save_roundtrip_links_and_warnings(client):
    items = [item("b1"), item("t1", "sensor_climate", x=3, y=3, w=0.35, h=0.35, link={"kind": "sensor", "id": "gh_temp_1"}, label="West T"),
             item("z1", "bed_hydro", link={"kind": "zone", "id": "hydro_1"}), item("tank", "tank", link={"kind": "tank", "id": "sim_tank"}),
             item("f1", "fan", x=4, y=4, w=0.8, h=0.8, link={"kind": "actuator", "id": "sim_valve_a"}, rotation=90)]
    r = client.put("/api/layout", json={"items": items, "grid_m": 0.25})
    assert r.status_code == 200 and r.json()["warnings"] == []
    d = client.get("/api/layout").json()
    assert len(d["items"]) == 5 and d["grid_m"] == 0.25 and d["items"][1]["link"] == {"kind": "sensor", "id": "gh_temp_1"}
    out = client.put("/api/layout", json={"items": [item("far", x=19.5, y=1, w=2, h=2)]}).json()
    assert "extends outside the 20 x 10 m" in out["warnings"][0]
    cfg = client.get("/api/config").json()
    cfg["length_m"] = 30
    client.put("/api/config", json=cfg)
    assert client.get("/api/layout").json()["warnings"] == []                          # dimensions are editable


def test_validation(client):
    put = lambda items: client.put("/api/layout", json={"items": items}).status_code  # noqa: E731
    assert put([item("a"), item("a")]) == 422                                           # duplicate id
    assert put([item(type_="spaceship")]) == 422
    assert put([item(link={"kind": "sensor", "id": "ghost"})]) == 422
    assert put([item(link={"kind": "robot", "id": "x"})]) == 422
    assert put([item(rotation=45)]) == 422
    assert put([item(w=0)]) == 422
    assert put([item(layer="nowhere")]) == 422
    assert put([item(id_="bad id!")]) == 422
    assert put([item(f"i{i}") for i in range(501)]) == 422
    assert put([]) == 200


def test_pdf_export(client):
    client.put("/api/layout", json={"items": [item("b1", label="Bed A"), item("t1", "sensor_climate", x=3, y=3, w=0.35, h=0.35,
                                                                          link={"kind": "sensor", "id": "gh_temp_1"}),
                                           item("l1", "light", x=2, y=2, w=1.2, h=0.3)]})
    client.app.state.ingest.latest["gh_temp_1"] = LatestValue(22.5, 1, 22.5)
    p = client.get("/api/layout/export.pdf", params={"readings": True})
    assert p.status_code == 200 and p.content[:5] == b"%PDF-" and len(p.content) > 1000
    assert b"22.5" in p.content or p.content.count(b"stream") > 0                       # drawn content present
    q = client.get("/api/layout/export.pdf", params={"layers": "lighting"})
    assert q.content[:5] == b"%PDF-"
    assert client.get("/api/layout/export.pdf").status_code == 200


@pytest.mark.parametrize("path", ["/api/plants", "/api/crops", "/api/layout", "/api/analytics/seasonal"])
def test_fresh_install_endpoints(client, path):
    assert client.get(path).status_code == 200
