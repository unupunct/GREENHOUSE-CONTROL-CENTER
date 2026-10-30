import asyncio
import time

import pytest

from app.hal import DriverError
from app.hal.simulated import SimulatedDriver
from app.services import troubleshoot
from app.services.ingest import LatestValue

MESSAGES = [
    ("no/partial response (0/5 bytes)", "modbus_timeout"), ("CRC mismatch (noise, wrong baud/parity, or two devices answering)", "modbus_crc"),
    ("device returned Modbus exception 2 (illegal data address)", "modbus_exception"), ("cannot open COM9: could not open port", "port_open"),
    ("bus 'rs485_9' is not configured", "bus_unconfigured"), ("serial error on bus 'rs485_1': device disconnected", "serial_error"),
    ("DS18B20 CRC check failed (wiring, pull-up or cable length?)", "ds18b20_crc"), ("DS18B20 returned 85.0 C (power-on value): check supply/pull-up", "ds18b20_85"),
    ("cannot read /sys/bus/w1/devices/28-1/w1_slave: [Errno 2]", "w1_missing"), ("SHT3x CRC error (wiring/pull-ups/cable length?)", "sht_crc"),
    ("I2C error at 0x44: [Errno 121]", "i2c_error"), ("value 9999.0 outside valid range [-20, 70]", "out_of_range"), ("GPIO 17: no module named gpiozero", "gpio_error"),
    ("tank level 5% is below the minimum 15%", "tank_low"), ("float switch reports low water", "tank_low"),
    ("tank level sensor has no fresh reading", "tank_no_reading"), ("no water source (tank) assigned", "tank_unassigned"),
    ("no open valve for this pump (dead-head protection)", "dead_head"), ("flow 0.10 L/min is below the minimum 5 (dry run or blockage)", "dry_run"),
    ("flow 60.00 L/min is above the maximum 40 (leak or burst pipe)", "burst"), ("Output 'fan1' was forced off at its maximum runtime (10s)", "max_runtime"),
    ("emergency stop is latched", "estop"), ("Cannot switch 'fan1' on: contactor offline", "output_error"),
    ("Cannot switch 'p1' OFF (relay offline). Cut power manually. Retrying.", "output_stuck"), ("safety limit exceeded: gh_temp_1 40 > 35", "safety_limit"),
    ("'heat' not switched on: requires circ to be on", "interlock"), ("Window 'v1' closing: wind above 10 m/s", "window_hazard"),
    ("Water is flowing (6.00 L/min) while all outputs are off: possible leak", "leak"), ("commissioning checks have not all passed", "gate"),
    ("automatic climate control is switched off", "auto_off"), ("Maintenance overdue: Clean the filter", "maintenance"),
]


@pytest.mark.parametrize("text,pid", MESSAGES)
def test_explains_the_messages_the_app_really_produces(text, pid):
    e = troubleshoot.explain(text)
    assert e["matched"] and e["id"] == pid, (text, e["id"])
    assert e["plain"] and e["likely_causes"] and e["what_to_check"] and e["docs"].endswith(".md")


def test_unknown_message_is_honest():
    e = troubleshoot.explain("flux capacitor desynchronised")
    assert not e["matched"] and "not one the assistant knows" in e["plain"]


def test_explain_real_errors_end_to_end(client):
    client.post("/api/sensors", json={"id": "mb1", "name": "m", "kind": "temperature", "zone": "soil", "unit": "C", "driver": "modbus_rtu",
                                      "address": {"bus": "nope", "slave": 1, "register": 0}})
    err = client.post("/api/sensors/mb1/test-read").json()["error"]
    assert troubleshoot.explain(err)["id"] == "bus_unconfigured"
    assert client.post("/api/diagnostics/explain", json={"text": err}).json()["id"] == "bus_unconfigured"
    asyncio.run(client.app.state.ingest.poll_once())                                    # raises a sensor_fault alert and an error event
    act = client.get("/api/diagnostics/explain/active").json()
    mine = [a for a in act["alerts"] if a["subject"] == "mb1"]
    assert mine and mine[0]["explanation"]["id"] == "bus_unconfigured"
    assert any(r["explanation"]["matched"] for r in act["recent"])
    errs = client.get("/api/diagnostics/errors", params={"days": 1, "source": "ingest"}).json()["events"]
    assert errs and errs[0]["explanation"]["matched"]
    assert client.get("/api/diagnostics/errors", params={"days": 0}).status_code == 422


def test_health_and_threshold_alerts(client):
    h = client.get("/api/diagnostics/health").json()
    names = {c["name"]: c for c in h["components"]}
    assert {"Storage", "Memory", "CPU temperature", "System clock", "Database", "Sensor polling", "Sensors", "Battery", "Emergency stop", "Commissioning", "Maintenance"} <= names.keys()
    assert names["Database"]["status"] == "ok" and names["System clock"]["status"] == "ok"
    assert names["Sensor polling"]["status"] == "crit"                                  # nothing polled yet in this test app
    asyncio.run(client.app.state.ingest.poll_once())
    h = client.get("/api/diagnostics/health").json()
    assert {c["name"]: c for c in h["components"]}["Sensor polling"]["status"] == "ok"
    s = client.get("/api/diagnostics/settings").json()
    assert client.put("/api/diagnostics/settings", json={**s, "cpu_temp_warn_c": 90, "cpu_temp_crit_c": 80}).status_code == 422
    assert client.put("/api/diagnostics/settings", json={**s, "disk_min_gb": 1_000_000}).status_code == 200
    assert {c["name"]: c for c in client.get("/api/diagnostics/health").json()["components"]}["Storage"]["status"] == "crit"
    client.post("/api/diagnostics/run")
    assert any(a["code"] == "system_health" and a["subject"] == "Storage" for a in client.get("/api/alerts").json())
    client.post("/api/diagnostics/run")
    assert len([a for a in client.get("/api/alerts").json() if a["code"] == "system_health"]) == 1
    client.put("/api/diagnostics/settings", json={**s, "disk_min_gb": 0.1})
    client.post("/api/diagnostics/run")
    assert not [a for a in client.get("/api/alerts").json() if a["code"] == "system_health" and a["subject"] == "Storage"]


def test_battery_threshold(client):
    client.post("/api/sensors", json={"id": "ups_v", "name": "UPS battery", "kind": "battery", "zone": "other", "unit": "V", "driver": "simulated", "address": {}})
    client.app.state.ingest.latest["ups_v"] = LatestValue(10.9, int(time.time()), 10.9)
    s = client.get("/api/diagnostics/settings").json()
    client.put("/api/diagnostics/settings", json={**s, "battery_min_v": 11.5})
    b = {c["name"]: c for c in client.get("/api/diagnostics/health").json()["components"]}["Battery"]
    assert b["status"] == "crit" and "10.9" in b["detail"]
    client.app.state.ingest.latest["ups_v"] = LatestValue(12.6, int(time.time()), 12.6)
    assert {c["name"]: c for c in client.get("/api/diagnostics/health").json()["components"]}["Battery"]["status"] == "ok"


def test_comms_counters(client, monkeypatch):
    ing = client.app.state.ingest
    asyncio.run(ing.poll_once())
    real = SimulatedDriver.read

    async def flaky(self, spec, now):
        if spec.id == "gh_co2_1":
            raise DriverError("no/partial response (0/5 bytes)")
        return await real(self, spec, now)

    monkeypatch.setattr(SimulatedDriver, "read", flaky)
    asyncio.run(ing.poll_once())
    asyncio.run(ing.poll_once())
    c = client.get("/api/diagnostics/comms").json()
    row = next(r for r in c["sensors"] if r["sensor_id"] == "gh_co2_1")
    assert row["ok"] == 1 and row["fail"] == 2 and row["success_pct"] == pytest.approx(33.3, abs=0.1) and "no/partial" in row["last_error"]
    ok = next(r for r in c["sensors"] if r["sensor_id"] == "gh_temp_1")
    assert ok["success_pct"] == 100.0 and ok["last_ms"] is not None and ok["simulated"]
    assert c["buses"][0]["bus"] == "simulated" and c["buses"][0]["fail"] == 2


# ------------------------------------------------------------ assistant

def _dx(client, kind, id_):
    r = client.post("/api/diagnostics/diagnose", json={"kind": kind, "id": id_})
    assert r.status_code == 200, r.text
    return r.json()


def test_diagnose_sensor(client):
    assert _dx(client, "sensor", "ghost")["verdict"] == "problem found"
    d = _dx(client, "sensor", "gh_temp_1")
    assert d["verdict"] == "problem found" and any("No reading" in f["text"] for f in d["findings"])
    asyncio.run(client.app.state.ingest.poll_once())
    d = _dx(client, "sensor", "gh_temp_1")
    assert d["verdict"] == "no problem found" and any("SIMULATED" in f["text"] for f in d["findings"])
    client.post("/api/sensors", json={"id": "mb1", "name": "m", "kind": "temperature", "zone": "soil", "unit": "C", "driver": "modbus_rtu",
                                      "address": {"bus": "nope", "slave": 1, "register": 0}})
    asyncio.run(client.app.state.ingest.poll_once())
    d = _dx(client, "sensor", "mb1")
    texts = " ".join(f["text"] for f in d["findings"])
    assert d["verdict"] == "problem found" and "bus 'nope' is not configured" in texts and "failed" in texts
    assert any("not configured" in s or "Add the bus" in s for s in d["next_steps"])
    client.post("/api/sensors", json={"id": "w1", "name": "w", "kind": "temperature", "zone": "hydroponic", "unit": "C", "driver": "ds18b20",
                                      "address": {"device_id": "28-0123456789ab"}})
    d = _dx(client, "sensor", "w1")
    assert any("1-Wire devices visible" in f["text"] and f["status"] == "problem" for f in d["findings"])
    client.put("/api/sensors/gh_temp_1", json={"id": "gh_temp_1", "name": "n", "kind": "temperature", "zone": "greenhouse", "unit": "C", "driver": "simulated", "enabled": False})
    assert any("DISABLED" in f["text"] for f in _dx(client, "sensor", "gh_temp_1")["findings"])


def test_diagnose_irrigation_output_and_zone(client):
    d = _dx(client, "output", "sim_pump")
    assert any("dead-head" in f["text"] for f in d["findings"] if f["status"] == "problem")
    assert any("Automatic control is not running" in f["text"] for f in d["findings"])
    eng = client.app.state.engine
    asyncio.run(eng.set_estop(time.time()))
    d = _dx(client, "output", "sim_valve_a")
    assert any("LATCHED" in f["text"] for f in d["findings"] if f["status"] == "problem")
    z = _dx(client, "zone", "soil_a")
    assert z["verdict"] == "problem found" and any("emergency stop" in f["text"].lower() for f in z["findings"])
    assert _dx(client, "zone", "ghost")["verdict"] == "problem found"


def test_diagnose_climate_output_and_window(client):
    client.post("/api/actuators", json={"id": "heat", "name": "Heater", "kind": "heater", "driver": "simulated_output", "max_runtime_s": 600,
                                        "interlocks": {"stop_if": {"sensor_id": "gh_temp_1", "above": 35}}})
    clim = client.app.state.climate
    clim.reload()
    clim._refusal_logged["heat"] = "safety limit exceeded: gh_temp_1 40 > 35"
    clim.blocked_until["heat"] = time.time() + 100
    d = _dx(client, "output", "heat")
    texts = [f["text"] for f in d["findings"] if f["status"] == "problem"]
    assert any("Blocked for another" in t for t in texts) and any("safety limit exceeded" in t for t in texts)
    assert any("safety limit" in s.lower() for s in d["next_steps"])
    client.post("/api/actuators", json={"id": "mo", "name": "o", "kind": "motor", "driver": "simulated_output", "max_runtime_s": 300})
    client.post("/api/actuators", json={"id": "mc", "name": "c", "kind": "motor", "driver": "simulated_output", "max_runtime_s": 300})
    client.post("/api/climate/windows", json={"id": "win1", "name": "Vent", "open_output_id": "mo", "close_output_id": "mc", "travel_time_s": 60})
    clim.reload()
    clim.win["win1"].hazard = "wind above 10 m/s"
    d = _dx(client, "window", "win1")
    assert d["verdict"] == "problem found" and any("wind" in f["text"] for f in d["findings"])
    assert any("Position unknown" in f["text"] for f in d["findings"])
    assert client.post("/api/diagnostics/diagnose", json={"kind": "toaster", "id": "x"}).status_code == 422
