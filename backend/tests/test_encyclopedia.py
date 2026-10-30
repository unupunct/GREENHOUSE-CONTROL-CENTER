import json

import pytest

from app.hal.outputs import OUTPUT_DRIVERS
from app.hal.registry import DRIVERS
from app.knowledge import hardware as hw

PART10 = ["Raspberry Pi models", "ESP32 models", "Temperature sensors", "Humidity sensors", "Soil moisture sensors", "CO2 sensors",
          "Light sensors", "PAR sensors", "pH probes", "EC probes", "Water-level sensors", "Flow meters", "Pumps", "Solenoid valves",
          "Fans", "Linear actuators", "Relays", "MOSFET drivers", "Power supplies", "UPS systems", "RS485 adapters", "Enclosures",
          "Connectors", "Cables", "Safety equipment"]


def test_all_part10_categories_covered_with_pages():
    titles = [c["title"] for c in hw.CATEGORIES]
    assert len(titles) == 25
    for want in PART10:
        assert any(want.lower().split()[0] in t.lower() for t in titles), want
    for c in hw.CATEGORIES:
        assert any(i["category"] == c["id"] for i in hw.ITEMS), c["id"]       # every category has at least one item page


def test_every_item_page_has_all_required_sections(client):
    for it in hw.ITEMS:
        p = client.get(f"/api/encyclopedia/{it['id']}").json()
        for s in hw.PAGE_SECTIONS:
            v = p["sections"][s]
            assert v and (v if isinstance(v, str) else all(v)), (it["id"], s)
        assert p["models"] and p["alternatives"] is not None and p["replacement"]["interval"] and p["replacement"]["basis"]
        assert p["compatibility"]["protocols"] and p["purchase"]["note"] and p["spec_note"]


def test_no_prices_or_links_in_static_data():
    text = json.dumps([hw.CATEGORIES, hw.ITEMS]).lower()
    for bad in ("http://", "https://", "www.", " ron", "lei", "price\":", "€", "$"):
        assert bad not in text, bad


def test_prices_only_from_recorded_offers(client):
    p = client.get("/api/encyclopedia/rpi5").json()
    assert p["purchase"]["offers"][0]["supplier"] == "Optimus Digital" and p["purchase"]["offers"][0]["price_ron_incl_vat"] == 639
    assert p["purchase"]["offers"][0]["url"].startswith("https://www.optimusdigital.ro/")
    assert client.get("/api/encyclopedia/rpi4").json()["purchase"]["offers"] == []      # not researched: no price shown
    assert client.get("/api/encyclopedia/soil_probe_analog").json()["purchase"]["offers"] == []


def test_specs_only_where_established_and_labelled(client):
    p = client.get("/api/encyclopedia/sht3x").json()
    assert any("0x44" in s["value"] for s in p["specs"]) and "verify" in p["spec_note"].lower()
    assert client.get("/api/encyclopedia/soil_probe_rs485").json()["specs"] == []
    assert "datasheet" in client.get("/api/encyclopedia/soil_probe_rs485").json()["spec_note"]
    unsure = client.get("/api/encyclopedia/irrigation_pump").json()
    assert unsure["specs"] == []


def test_search_and_filter(client):
    r = client.get("/api/encyclopedia", params={"q": "modbus"}).json()["items"]
    assert any(i["id"] == "soil_probe_rs485" for i in r) or any("RS485" in " ".join(i["interface"]) for i in r)
    assert client.get("/api/encyclopedia", params={"q": "zzzznothing"}).json()["items"] == []
    cat = client.get("/api/encyclopedia", params={"category": "ph"}).json()["items"]
    assert [i["id"] for i in cat] == ["ph_transmitter"]
    assert len(client.get("/api/encyclopedia").json()["items"]) == len(hw.ITEMS)
    assert client.get("/api/encyclopedia/nope").status_code == 404


def test_compatibility_answers():
    c = lambda i: hw.compat(hw.ITEM_BY_ID[i])  # noqa: E731
    assert c("sht3x")["can_connect_to_pi"] == "directly" and c("sht3x")["protocols"] == ["I2C"] and not c("sht3x")["needs_adc"]
    assert c("sht3x")["esp32"] == "yes" and not c("sht3x")["needs_external_power"]
    soil = c("soil_probe_analog")
    assert soil["needs_adc"] and soil["can_connect_to_pi"] == "with_adapter" and "ADC" in soil["adapters_needed"][0]
    rs = c("soil_probe_rs485")
    assert rs["can_connect_to_pi"] == "with_adapter" and "USB-RS485" in rs["adapters_needed"][0] and rs["needs_external_power"]
    assert "RS485" in rs["protocols"][0] and "transceiver" in rs["esp32"]
    assert c("flow_pulse")["can_connect_to_pi"] == "with_adapter" and "Level shifter" in c("flow_pulse")["adapters_needed"][0]
    assert c("irrigation_pump")["can_connect_to_pi"] == "not_applicable" and any("mains" in w.lower() or "driver" in w.lower() for w in c("irrigation_pump")["warnings"])
    assert any("GPIO is 3.3 V" in w for w in c("mosfet_driver_24v")["warnings"])
    assert c("float_switch")["can_connect_to_pi"] == "directly"
    assert any("mains" in w.lower() for w in c("led_grow_light")["warnings"])


def test_supported_flag_follows_real_drivers():
    for it in hw.ITEMS:
        if it["driver"]:
            assert it["driver"] in DRIVERS or it["driver"] in OUTPUT_DRIVERS, (it["id"], it["driver"])
            sup = hw.compat(it)["supported_by_application"]
            assert sup["hardware_tested"] is False                     # nothing has been tested on real hardware
    assert hw.compat(hw.ITEM_BY_ID["scd41"])["supported_by_application"] is None   # honest: no SCD41 driver yet
    assert hw.compat(hw.ITEM_BY_ID["esp32_devkit"])["supported_by_application"] is None


def test_custom_compat_endpoint(client):
    r = client.post("/api/encyclopedia/compatibility/check", json={"interface": ["analog_voltage"], "supply": "5 V"}).json()
    assert r["needs_adc"] and r["can_connect_to_pi"] == "with_adapter"
    r = client.post("/api/encyclopedia/compatibility/check", json={"interface": ["i2c"], "external_power": True}).json()
    assert r["can_connect_to_pi"] == "directly" and r["needs_external_power"]
    assert client.post("/api/encyclopedia/compatibility/check", json={"interface": ["telepathy"]}).status_code == 422
    assert client.post("/api/encyclopedia/compatibility/check", json={"interface": []}).status_code == 422


def test_used_in_your_system_lists_registered_hardware(client):
    p = client.get("/api/encyclopedia/sim_nothing") if False else client.get("/api/encyclopedia/ds18b20").json()
    assert p["used_in_your_system"] == []
    client.post("/api/sensors", json={"id": "wt1", "name": "w", "kind": "temperature", "zone": "hydroponic", "unit": "C",
                                      "driver": "ds18b20", "address": {"device_id": "28-0123456789ab"}})
    assert client.get("/api/encyclopedia/ds18b20").json()["used_in_your_system"] == ["wt1"]
    pytest.importorskip("fastapi")
