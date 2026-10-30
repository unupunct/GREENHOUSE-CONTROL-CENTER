import io
import time

import pytest

from app.services.ingest import LatestValue

ALL_INPUTS = {"height_m": 3.5, "ridge_height_m": 5.0, "orientation": "north_south", "construction": "polycarbonate", "heating_required": True,
              "water_pressure_bar": 3.0, "electricity_supply": "single_phase_230v", "latitude": 44.4, "longitude": 26.1}


def steps(client):
    return {s["id"]: s for s in client.get("/api/wizard").json()["steps"]}


def fresh(client, sid, v=1.0):
    client.app.state.ingest.latest[sid] = LatestValue(v, int(time.time()), v)


# ---------------------------------------------------------------- wizard

def test_default_state_is_computed_from_the_system(client):
    w = client.get("/api/wizard").json()
    ids = [s["id"] for s in w["steps"]]
    assert ids[:2] == ["greenhouse", "plan_hardware"] and "commissioning" in ids and ids[-1] == "manual_generated"
    s = {x["id"]: x for x in w["steps"]}
    assert s["greenhouse"]["status"] == "in_progress" and len(s["greenhouse"]["questions"]) == 8     # nothing is assumed: it asks
    assert any("height" in q["label"].lower() for q in s["greenhouse"]["questions"])
    assert s["pi_prepare"]["status"] == "not_applicable"                                            # not a Raspberry Pi
    assert s["software_install"]["status"] == "todo" and "Simulation mode is ON" in s["software_install"]["detail"]
    assert s["sensors"]["status"] == "todo" and "No real" in s["sensors"]["detail"]
    assert s["commissioning"]["status"] == "todo" and s["automation"]["status"] == "blocked"   # demo outputs exist, so checks apply
    assert s["calibration"]["status"] == "not_applicable"
    assert w["next"] == "greenhouse" and w["progress"]["done"] == 0
    assert all(st["commands"] for st in (s["pi_prepare"], s["software_install"])) and "apt" in s["pi_prepare"]["commands"][1]["cmd"]


def test_greenhouse_step_follows_engineering_inputs(client):
    cfg = client.get("/api/config").json()
    client.put("/api/config", json={**cfg, **ALL_INPUTS})
    assert steps(client)["greenhouse"]["status"] == "done"
    client.put("/api/config", json={**cfg, **ALL_INPUTS, "height_m": None})
    s = steps(client)["greenhouse"]
    assert s["status"] == "in_progress" and [q["label"] for q in s["questions"]] == ["Gutter height"]


def test_sensor_and_calibration_steps_track_real_hardware(client):
    client.put("/api/hardware/buses", json=[{"id": "rs485_1", "port": "COM9"}])
    client.post("/api/sensors", json={"id": "ph1", "name": "pH", "kind": "ph", "zone": "hydroponic", "unit": "pH", "driver": "modbus_rtu",
                                      "address": {"bus": "rs485_1", "slave": 2, "register": 0}})
    s = steps(client)
    assert s["sensors"]["status"] == "in_progress" and "silent: ph1" in s["sensors"]["detail"]       # simulated sensors do not count
    assert s["calibration"]["status"] == "in_progress" and "ph1" in s["calibration"]["detail"]
    fresh(client, "ph1", 6.0)
    assert steps(client)["sensors"]["status"] == "done"
    client.post("/api/sensors/ph1/calibration", json={"method": "manual", "gain": 1.0, "offset": 0.1})
    assert steps(client)["calibration"]["status"] == "done"


def test_outputs_zone_issue_and_commissioning_progress(client):
    client.post("/api/actuators", json={"id": "rv", "name": "v", "kind": "valve", "driver": "gpio_output", "max_runtime_s": 60, "address": {"pin": 17}})
    s = steps(client)
    assert s["outputs"]["status"] == "done" and "1 real output" in s["outputs"]["detail"]
    assert s["commissioning"]["status"] in ("todo", "in_progress") and "applicable checks passed" in s["commissioning"]["detail"]
    assert s["automation"]["status"] == "blocked"


def test_manual_steps_need_a_real_note_and_only_for_manual_steps(client):
    assert client.post("/api/wizard/greenhouse/confirm", json={"note": "I did it all just now"}).status_code == 422   # computed step
    assert client.post("/api/wizard/wiring_checked/confirm", json={"note": "ok"}).status_code == 422
    assert client.post("/api/wizard/wiring_checked/confirm", json={"note": "polarity and A/B checked on every device"}).status_code == 200
    s = steps(client)["wiring_checked"]
    assert s["status"] == "done" and s["attested"]["note"].startswith("polarity")
    assert client.delete("/api/wizard/wiring_checked/confirm").status_code == 200
    assert steps(client)["wiring_checked"]["status"] == "todo"
    client.post("/api/wizard/electrician_signoff/confirm", json={"note": "licensed electrician signed it off"})
    assert steps(client)["electrician_signoff"]["status"] == "done"


def test_maintenance_step_and_progress_and_next(client):
    client.post("/api/maintenance", json={"title": "Check the filter", "interval_days": 30})
    assert steps(client)["maintenance"]["status"] == "done"
    w = client.get("/api/wizard").json()
    assert w["progress"]["done"] == 1 and w["next"] == "greenhouse"
    cfg = client.get("/api/config").json()
    client.put("/api/config", json={**cfg, **ALL_INPUTS})
    assert client.get("/api/wizard").json()["next"] == "plan_hardware"


# ---------------------------------------------------------------- manual

def _dl(client, fmt, **q):
    r = client.get(f"/api/manual/download.{fmt}", params=q)
    assert r.status_code == 200, r.text
    return r


def test_manual_without_real_hardware_does_not_print_generic_wiring(client):
    md = _dl(client, "md").text
    assert "No real (non-simulated) sensors or outputs are registered yet" in md
    assert "SIMULATED" in md and "Nothing to assemble yet" in md
    assert "daisy-chain" not in md and "4.7" not in md                           # no generic wiring instructions
    assert "Raspberry Pi 5, 4 GB" in md and "639.00 RON (verified)" in md          # but the equipment list and the one real offer are there
    assert "No electrical loads were entered" in md
    assert "Not provided (so dependent calculations are not final)" in md          # unknown greenhouse facts are flagged
    p = client.get("/api/manual/preview").json()
    assert p["real_sensors"] == 0 and "instead of printing generic" in p["note"] and len(p["sections"]) == 11


def _equip(client):
    client.put("/api/config", json={**client.get("/api/config").json(), **ALL_INPUTS})
    client.put("/api/hardware/buses", json=[{"id": "rs485_1", "port": "/dev/ttyUSB0", "baudrate": 19200, "parity": "E"}])
    client.post("/api/sensors", json={"id": "ph_main", "name": "Nutrient pH", "kind": "ph", "zone": "hydroponic", "unit": "pH", "driver": "modbus_rtu",
                                      "address": {"bus": "rs485_1", "slave": 7, "function": 3, "register": 40}})
    client.post("/api/sensors", json={"id": "sht_west", "name": "West T", "kind": "temperature", "zone": "greenhouse", "unit": "C", "driver": "sht3x",
                                      "address": {"bus": 1, "i2c_address": 68}})
    client.post("/api/sensors", json={"id": "tank_float", "name": "Tank float", "kind": "float_switch", "zone": "water", "unit": "state", "driver": "gpio_input",
                                      "address": {"pin": 22}})
    client.post("/api/actuators", json={"id": "valve_n", "name": "North valve", "kind": "valve", "driver": "gpio_output", "max_runtime_s": 600, "address": {"pin": 17}})
    client.post("/api/actuators", json={"id": "relay_fan", "name": "Fan relay", "kind": "fan", "driver": "modbus_coil", "max_runtime_s": 3600,
                                        "address": {"bus": "rs485_1", "slave": 3, "coil": 1}})
    client.post("/api/actuators", json={"id": "mo", "name": "o", "kind": "motor", "driver": "gpio_output", "max_runtime_s": 300, "address": {"pin": 23}})
    client.post("/api/actuators", json={"id": "mc", "name": "c", "kind": "motor", "driver": "gpio_output", "max_runtime_s": 300, "address": {"pin": 24}})
    client.post("/api/climate/windows", json={"id": "vent1", "name": "Ridge vent", "open_output_id": "mo", "close_output_id": "mc", "travel_time_s": 90,
                                              "open_limit_sensor_id": "tank_float", "rain_sensor_id": "tank_float"})
    client.post("/api/maintenance", json={"title": "Calibrate pH probe", "interval_days": 30})


def test_manual_describes_the_actual_configuration(client):
    _equip(client)
    md = _dl(client, "md").text
    assert "No real (non-simulated) sensors" not in md and "Nothing to assemble" not in md
    assert "RS485 bus 'rs485_1' (/dev/ttyUSB0, 19200 baud, parity E, 1 stop bit)" in md
    assert "| rs485_1 | 7 | 3 | 40 | int16 | ph_main |" in md                                  # Modbus address row
    assert "BCM 17 -> valve_n" in md and "Modbus" in md and "SDA GPIO2 (pin 3)" in md and "float switch" in md
    assert "Ridge vent" in md and "travel 90 s" in md and "| relay_fan | fan | modbus_coil |" in md
    assert "pH 7.00 and 4.01 buffers" in md and "none recorded" in md                           # calibration section for the real pH probe
    assert "Calibrate pH probe" in md and "```mermaid" in md and "RS485" in md
    assert "SIMULATED" in md                                                                    # demo sensors still flagged
    assert "Not provided" not in md                                                             # all engineering inputs were supplied
    assert "daisy-chain" in md and "isolated" in md.lower()


def test_manual_formats_and_tier(client):
    _equip(client)
    html = _dl(client, "html").text
    assert html.startswith("<!doctype html>") and "<svg" in html and "ph_main <tspan" in html and "(sensor)" in html
    assert "<script" not in html.lower()                                                        # works offline
    pdf = _dl(client, "pdf").content
    assert pdf[:5] == b"%PDF-" and len(pdf) > 5000
    low = _dl(client, "md", tier="low").text
    pro = _dl(client, "md", tier="professional").text
    assert "for the low configuration" in low and "for the professional configuration" in pro and len(pro) > len(low)
    assert client.get("/api/manual/download.doc").status_code == 422
    assert client.get("/api/manual/download.md", params={"tier": "ultra"}).status_code == 422


def test_printable_checklists(client):
    _equip(client)
    md = _dl(client, "md", kind="checklist").text
    assert "## Components" in md and "## Registered devices" in md and "## Commissioning" in md and "## Sign-off" in md
    assert "sensor ph_main" in md and "output valve_n (valve)" in md and "output relay_fan (fan)" in md
    assert "| [ ] |" in md or "[ ]" in md and "Qualified electrician (mains)" in md
    html = _dl(client, "html", kind="checklist").text
    assert "@media print" in html and "Installer" in html
    assert _dl(client, "pdf", kind="checklist").content[:5] == b"%PDF-"
    assert client.get("/api/manual/preview", params={"kind": "checklist"}).json()["sections"][0]["heading"] == "Components"


def test_regenerating_reflects_changes(client):
    _equip(client)
    assert "late_probe" not in _dl(client, "md").text
    client.post("/api/sensors", json={"id": "late_probe", "name": "Late probe", "kind": "ec", "zone": "hydroponic", "unit": "mS/cm", "driver": "modbus_rtu",
                                      "address": {"bus": "rs485_1", "slave": 8, "register": 2}})
    md = _dl(client, "md").text
    assert "late_probe" in md and "EC standard solution" in md
    client.delete("/api/sensors/late_probe")
    assert "late_probe" not in _dl(client, "md").text


def test_electrical_section_uses_entered_loads(client):
    opts = client.get("/api/planner/options").json()["options"]
    opts["loads"] = [{"name": "valve", "power_w": 10, "voltage": "24VDC", "qty": 4}, {"name": "fan", "power_w": 400, "voltage": "230VAC", "qty": 1}]
    client.put("/api/planner/options", json=opts)
    md = _dl(client, "md").text
    assert "at least 50 W" in md and "| valve | 0.42 | 1 A |" in md and "230VAC 400 W" in md and "electrician" in md.lower()
    pytest.importorskip("reportlab")
    assert io.BytesIO(_dl(client, "pdf").content).read(4) == b"%PDF"
