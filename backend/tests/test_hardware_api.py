import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app.hal import HalContext
from app.main import create_app
from tests.fakes import FakeSht3x, make_bus_manager, make_i2c_manager


@pytest.fixture
def hw(settings, tmp_path):
    """App with emulated Modbus (slave 7: reg 0 = 215 -> 21.5 C after scale 0.1) and SHT3x."""
    buses, transports = make_bus_manager({7: {(3, 0): 215, (3, 1): 600, (4, 5): 1}})
    sht = FakeSht3x(21.5, 55.0)
    w1 = tmp_path / "w1"
    (w1 / "28-0123456789ab").mkdir(parents=True)
    (w1 / "28-0123456789ab" / "w1_slave").write_text(
        "72 01 4b 46 7f ff 0e 10 57 : crc=57 YES\n72 01 4b 46 7f ff 0e 10 57 t=23125\n")
    ctx = HalContext(buses=buses, i2c=make_i2c_manager(sht), w1_dir=w1)
    app = create_app(settings, ctx)
    with TestClient(app) as c:
        c.sht, c.w1, c.transports = sht, w1, transports
        c.put("/api/hardware/buses", json=[{"id": "rs485_1", "port": "FAKE", "baudrate": 9600}])
        yield c


MODBUS_T = {"id": "gh_mb_temp", "name": "Modbus temp", "kind": "temperature", "zone": "greenhouse",
            "unit": "°C", "driver": "modbus_rtu", "min_valid": -20, "max_valid": 70,
            "address": {"bus": "rs485_1", "slave": 7, "function": 3, "register": 0,
                        "datatype": "int16", "scale": 0.1}}


def test_drivers_listed_and_untested_flag(hw):
    d = hw.get("/api/hardware/drivers").json()
    names = {x["name"]: x for x in d["drivers"]}
    assert {"simulated", "modbus_rtu", "ds18b20", "sht3x"} <= names.keys()
    assert not any(x["hardware_tested"] for x in names.values())


def test_modbus_sensor_end_to_end_with_calibration(hw):
    assert hw.post("/api/sensors", json=MODBUS_T).status_code == 201
    r = hw.post("/api/sensors/gh_mb_temp/test-read").json()
    assert r["ok"] and r["raw"] == 21.5 and r["calibrated"] == 21.5

    # poll stores calibrated value; one-point calibration from the live raw reading
    asyncio.run(hw.app.state.ingest.poll_once())
    assert hw.app.state.ingest.latest["gh_mb_temp"].value == 21.5
    c = hw.post("/api/sensors/gh_mb_temp/calibration",
                json={"method": "one_point", "reference": 22.3}).json()
    assert c["gain"] == 1.0 and abs(c["offset"] - 0.8) < 1e-9
    asyncio.run(hw.app.state.ingest.poll_once())
    assert abs(hw.app.state.ingest.latest["gh_mb_temp"].value - 22.3) < 1e-6
    assert hw.app.state.ingest.latest["gh_mb_temp"].raw == 21.5

    hist = hw.get("/api/sensors/gh_mb_temp/calibration").json()
    assert hist[0]["method"] == "one_point"
    hw.post("/api/sensors/gh_mb_temp/calibration", json={"method": "reset"})
    assert hw.post("/api/sensors/gh_mb_temp/test-read").json()["calibrated"] == 21.5


def test_two_point_calibration(hw):
    hw.post("/api/sensors", json=MODBUS_T)
    r = hw.post("/api/sensors/gh_mb_temp/calibration", json={
        "method": "two_point", "raw1": 0.2, "ref1": 0.0, "raw2": 100.4, "ref2": 100.0}).json()
    assert abs(r["gain"] * 0.2 + r["offset"]) < 1e-9
    assert abs(r["gain"] * 100.4 + r["offset"] - 100) < 1e-9
    bad = hw.post("/api/sensors/gh_mb_temp/calibration", json={
        "method": "two_point", "raw1": 5, "ref1": 0, "raw2": 5, "ref2": 100})
    assert bad.status_code == 422
    insane = hw.post("/api/sensors/gh_mb_temp/calibration", json={
        "method": "manual", "gain": 50, "offset": 0})
    assert insane.status_code == 422


def test_address_conflict_and_validation(hw):
    hw.post("/api/sensors", json=MODBUS_T)
    dup = {**MODBUS_T, "id": "other"}
    assert hw.post("/api/sensors", json=dup).status_code == 409
    other_reg = {**MODBUS_T, "id": "other", "address": {**MODBUS_T["address"], "register": 1}}
    assert hw.post("/api/sensors", json=other_reg).status_code == 201
    bad = {**MODBUS_T, "id": "bad1", "address": {**MODBUS_T["address"], "slave": 300}}
    assert hw.post("/api/sensors", json=bad).status_code == 422
    assert hw.post("/api/sensors", json={**MODBUS_T, "id": "bad2", "driver": "nope"}).status_code == 422
    # driver/kind restrictions
    sht_bad = {"id": "x_sht", "name": "x", "kind": "co2", "zone": "greenhouse", "unit": "ppm",
               "driver": "sht3x", "address": {"bus": 1, "i2c_address": 0x44}}
    assert hw.post("/api/sensors", json=sht_bad).status_code == 422


def test_bus_failure_raises_alert_not_crash(hw):
    hw.post("/api/sensors", json={**MODBUS_T, "address": {**MODBUS_T["address"], "slave": 9}})
    asyncio.run(hw.app.state.ingest.poll_once())
    alerts = hw.get("/api/alerts").json()
    assert any(a["subject"] == "gh_mb_temp" for a in alerts)
    assert hw.post("/api/sensors/gh_mb_temp/test-read").json()["ok"] is False


def test_unconfigured_bus_is_clear_error(hw):
    t = {**MODBUS_T, "address": {**MODBUS_T["address"], "bus": "ghost"}}
    hw.post("/api/sensors", json=t)
    r = hw.post("/api/sensors/gh_mb_temp/test-read").json()
    assert not r["ok"] and "not configured" in r["error"]


def test_scan_finds_devices_and_reports_crc_and_exception(hw):
    r = hw.post("/api/hardware/buses/rs485_1/scan",
                json={"start": 5, "end": 8, "function": 3, "register": 0}).json()
    assert [(f["slave"], f["result"]) for f in r["found"]] == [(7, "responded")]
    r = hw.post("/api/hardware/buses/rs485_1/scan",
                json={"start": 7, "end": 7, "function": 3, "register": 77}).json()
    assert r["found"][0]["result"] == "responded_with_exception"
    assert hw.post("/api/hardware/buses/rs485_1/scan", json={"start": 1, "end": 100}).status_code == 422


def test_bus_config_validation(hw):
    dup = [{"id": "a", "port": "P1"}, {"id": "a", "port": "P2"}]
    assert hw.put("/api/hardware/buses", json=dup).status_code == 422
    same_port = [{"id": "a", "port": "P1"}, {"id": "b", "port": "P1"}]
    assert hw.put("/api/hardware/buses", json=same_port).status_code == 422
    assert hw.get("/api/hardware/buses").json()[0]["id"] == "rs485_1"  # unchanged


def test_ds18b20(hw):
    assert hw.get("/api/hardware/1wire/devices").json()["devices"] == ["28-0123456789ab"]
    body = {"id": "water_t", "name": "Water", "kind": "temperature", "zone": "hydroponic",
            "unit": "°C", "driver": "ds18b20", "address": {"device_id": "28-0123456789ab"}}
    assert hw.post("/api/sensors", json=body).status_code == 201
    assert hw.post("/api/sensors/water_t/test-read").json()["raw"] == 23.125
    (hw.w1 / "28-0123456789ab" / "w1_slave").write_text("00 00 : crc=00 NO\n00 t=0\n")
    assert "CRC" in hw.post("/api/sensors/water_t/test-read").json()["error"]
    (hw.w1 / "28-0123456789ab" / "w1_slave").write_text("50 05 : crc=1 YES\n50 05 t=85000\n")
    assert "85" in hw.post("/api/sensors/water_t/test-read").json()["error"]
    bad = {**body, "id": "w2", "address": {"device_id": "10-abc"}}
    assert hw.post("/api/sensors", json=bad).status_code == 422


def test_sht3x_temperature_and_humidity_share_one_measurement(hw):
    base = {"zone": "greenhouse", "driver": "sht3x", "address": {"bus": 1, "i2c_address": 68}}
    hw.post("/api/sensors", json={**base, "id": "sht_t", "name": "T", "kind": "temperature", "unit": "°C"})
    hw.post("/api/sensors", json={**base, "id": "sht_h", "name": "H", "kind": "humidity", "unit": "%"})
    asyncio.run(hw.app.state.ingest.poll_once())
    lt, lh = hw.app.state.ingest.latest["sht_t"].value, hw.app.state.ingest.latest["sht_h"].value
    assert abs(lt - 21.5) < 0.01 and abs(lh - 55.0) < 0.01
    # (other seeded simulated sensors don't touch the fake) -> exactly one I2C transaction
    assert hw.sht.calls == 1
    hw.sht.corrupt = True
    hw.app.state.drivers.get("sht3x")._cache.clear()
    assert "CRC" in hw.post("/api/sensors/sht_t/test-read").json()["error"]


def test_delete_sensor_removes_history(hw):
    ing = hw.app.state.ingest
    asyncio.run(ing.poll_once())
    ing.flush(time.time())
    assert hw.delete("/api/sensors/gh_temp_1").status_code == 200
    assert hw.get("/api/readings/history", params={"sensor_id": "gh_temp_1"}).status_code == 404
    assert hw.delete("/api/sensors/gh_temp_1").status_code == 404
