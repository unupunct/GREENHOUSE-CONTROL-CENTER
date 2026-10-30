import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app.automation import rules
from app.hal import HalContext
from app.hal.outputs import SimulatedOutput
from app.main import create_app
from app.services.ingest import LatestValue
from tests.fakes import make_bus_manager

T0 = 1_800_000_000.0  # arbitrary fixed clock


# --------------------------------------------------------------- pure rules

def test_tank_rules_fail_safe():
    R = rules.TankReading
    assert rules.tank_ok(R(50, 1, None, None, True, False), 15, 20) == (True, "ok")
    assert not rules.tank_ok(R(10, 1, None, None, True, False), 15, 20)[0]
    assert not rules.tank_ok(R(50, 99, None, None, True, False), 15, 20)[0]       # stale
    assert not rules.tank_ok(R(None, None, None, None, True, False), 15, 20)[0]   # no reading
    assert not rules.tank_ok(R(None, None, 0.0, 1, False, True), 15, 20)[0]       # float low
    assert not rules.tank_ok(R(), 15, 20)[0]                                      # nothing configured


def test_start_refusals_and_limits():
    ok = (True, "ok")
    assert rules.start_refusals(kind="pump", estop=False, tank_ok_result=ok, needs_tank=True, valve_ready_for_pump=True) == []
    assert "dead-head" in " ".join(rules.start_refusals(kind="pump", estop=False, tank_ok_result=ok,
                                                       needs_tank=True, valve_ready_for_pump=False))
    assert rules.start_refusals(kind="valve", estop=True, tank_ok_result=None, needs_tank=False, valve_ready_for_pump=True)
    assert rules.runtime_exceeded(0, 11, 10) and not rules.runtime_exceeded(0, 10, 10)
    assert rules.flow_violation(pump_running_s=5, grace_s=10, flow_lpm=0, flow_age_s=1, min_lpm=5, max_lpm=None, max_age_s=20) is None
    assert "dry run" in rules.flow_violation(pump_running_s=15, grace_s=10, flow_lpm=1, flow_age_s=1, min_lpm=5, max_lpm=None, max_age_s=20)
    assert "leak" in rules.flow_violation(pump_running_s=15, grace_s=10, flow_lpm=50, flow_age_s=1, min_lpm=5, max_lpm=40, max_age_s=20)
    assert "fresh" in rules.flow_violation(pump_running_s=15, grace_s=10, flow_lpm=10, flow_age_s=99, min_lpm=5, max_lpm=40, max_age_s=20)
    assert rules.flow_violation(pump_running_s=99, grace_s=10, flow_lpm=0, flow_age_s=1, min_lpm=None, max_lpm=None, max_age_s=20) is None
    assert rules.leak_suspected(outputs_idle=True, flow_lpm=3, threshold_lpm=1, idle_flow_s=60, confirm_s=60)
    assert not rules.leak_suspected(outputs_idle=False, flow_lpm=3, threshold_lpm=1, idle_flow_s=60, confirm_s=60)


# ------------------------------------------------------------------ helpers

class Rig:
    """Drives the engine with a fake clock; sensors mirror the simulated plant."""

    def __init__(self, client: TestClient):
        self.c, self.e = client, client.app.state.engine
        self.ingest, self.plant = client.app.state.ingest, client.app.state.ctx.plant
        self.t = T0
        self.e.clock = lambda: self.t
        self.stale: set[str] = set()
        self.e.cfg.g.valve_settle_s  # config loaded

    def feed(self):
        p = self.plant
        p.advance(self.t)
        vals = {"sim_tank_level": p.tank_level_pct, "sim_flow_main": p.flow_lpm(),
                "sim_tank_float": 1.0 if p.tank_level_pct >= 10 else 0.0}
        for sid, v in vals.items():
            if sid not in self.stale:
                self.ingest.latest[sid] = LatestValue(v, int(self.t), v)

    def step(self, seconds=1, n=1):
        for _ in range(n):
            self.t += seconds
            self.feed()
            asyncio.run(self.e.tick(self.t))

    def run_zone(self, zone="soil_a", duration=20):
        self.feed()
        return asyncio.run(self.e.start_zone(zone, duration, "manual", self.t))

    def alerts(self):
        return [a["code"] for a in self.c.get("/api/alerts").json()]


@pytest.fixture
def rig(client):
    client.app.state.engine.reload()
    r = Rig(client)
    r.feed()
    asyncio.run(client.app.state.engine.startup(T0))
    return r


# ------------------------------------------------------------- engine runs

def test_demo_equipment_is_seeded(client):
    s = client.get("/api/irrigation/setup").json()
    assert {z["id"] for z in s["zones"]} == {"soil_a", "hydro_1"}
    assert {a["id"] for a in s["actuators"]} == {"sim_pump", "sim_valve_a", "sim_valve_b"}
    assert all(a["max_runtime_s"] > 0 for a in s["actuators"])


def test_zone_run_sequence_and_volume(rig):
    ok, msg = rig.run_zone(duration=20)
    assert ok, msg
    st = rig.e.status(rig.t)
    assert st["outputs"]["sim_valve_a"]["on"] and not st["outputs"]["sim_pump"]["on"]  # valve first
    rig.step(1, 2)
    assert not rig.e.status(rig.t)["outputs"]["sim_pump"]["on"]  # still settling (3 s)
    rig.step(1, 2)
    st = rig.e.status(rig.t)
    assert st["outputs"]["sim_pump"]["on"] and st["zones"][0]["running"]["phase"] == "running"
    rig.step(1, 25)  # run completes
    st = rig.e.status(rig.t)
    assert not any(o["on"] for o in st["outputs"].values()) and not rig.e.jobs
    runs = rig.c.get("/api/irrigation/history").json()["runs"]
    assert runs[0]["end_reason"] == "completed" and runs[0]["actual_s"] >= 20
    assert 5 < runs[0]["volume_l"] < 9  # ~20 L/min for ~20 s, measured by the flow sensor
    assert runs[0]["volume_estimate_l"] is not None


def test_stop_zone_closes_pump_then_valve(rig):
    rig.run_zone(duration=60)
    rig.step(1, 6)
    assert rig.e.stop_zone("soil_a", rig.t)
    rig.step(1, 1)
    o = rig.e.status(rig.t)["outputs"]
    assert not o["sim_pump"]["on"] and o["sim_valve_a"]["on"]  # pump off first
    rig.step(1, 4)
    assert not any(v["on"] for v in rig.e.status(rig.t)["outputs"].values())


def test_low_tank_refuses_start_and_stops_run(rig):
    rig.plant.tank_level_pct = 5
    ok, msg = rig.run_zone()
    assert not ok and "below the minimum" in msg
    rig.plant.tank_level_pct = 60
    assert rig.run_zone(duration=120)[0]
    rig.step(1, 6)
    assert rig.e.status(rig.t)["outputs"]["sim_pump"]["on"]
    rig.plant.tank_level_pct = 5
    rig.step(1, 2)
    assert not any(v["on"] for v in rig.e.status(rig.t)["outputs"].values())
    assert "irrigation_fault" in rig.alerts()
    assert "below the minimum" in rig.c.get("/api/irrigation/history").json()["runs"][0]["end_reason"]


def test_stale_tank_sensor_stops_run(rig):
    rig.run_zone(duration=120)
    rig.step(1, 6)
    rig.stale = {"sim_tank_level", "sim_tank_float"}
    rig.step(1, 25)  # readings age beyond the 20 s limit
    assert not rig.e.status(rig.t)["outputs"]["sim_pump"]["on"]
    assert "no fresh reading" in rig.c.get("/api/irrigation/history").json()["runs"][0]["end_reason"]


def test_dry_run_detected(rig):
    rig.e.cfg.actuators["sim_pump"]["address"]["sim_flow_lpm"] = 0.0  # pump runs but moves no water
    rig.run_zone(duration=120)
    rig.step(1, 20)
    assert not any(v["on"] for v in rig.e.status(rig.t)["outputs"].values())
    assert "dry run" in rig.c.get("/api/irrigation/history").json()["runs"][0]["end_reason"]


def test_burst_pipe_detected(rig):
    rig.run_zone(duration=120)
    rig.step(1, 12)  # past the 8 s flow grace period
    rig.plant.leak_lpm = 40  # flow now above the 40 L/min maximum
    rig.step(1, 2)
    assert not any(v["on"] for v in rig.e.status(rig.t)["outputs"].values())
    assert "leak or burst" in rig.c.get("/api/irrigation/history").json()["runs"][0]["end_reason"]


def test_max_runtime_is_a_hard_ceiling(rig):
    a = next(x for x in rig.c.get("/api/irrigation/setup").json()["actuators"] if x["id"] == "sim_valve_b")
    a["max_runtime_s"] = 10
    assert rig.c.put("/api/actuators/sim_valve_b", json=a).status_code == 200
    r = rig.c.post("/api/actuators/sim_valve_b/command", json={"state": "on", "duration_s": 9999})
    assert r.status_code == 200 and "10s" in r.json()["detail"]  # duration clipped to the ceiling
    rig.step(1, 5)
    assert rig.e.status(rig.t)["outputs"]["sim_valve_b"]["on"]
    rig.step(1, 8)
    assert not rig.e.status(rig.t)["outputs"]["sim_valve_b"]["on"]


def test_forced_off_when_runtime_exceeded_even_if_hold_extended(rig):
    asyncio.run(rig.e.hold("sim_valve_b", True, 5, rig.t))
    rig.e.holds["sim_valve_b"].until = rig.t + 100_000  # something tried to extend it
    rig.e.cfg.actuators["sim_valve_b"]["max_runtime_s"] = 10
    rig.step(1, 12)
    assert not rig.e.status(rig.t)["outputs"]["sim_valve_b"]["on"]
    assert "max_runtime" in rig.alerts()


def test_dead_head_protection_for_manual_pump(rig):
    r = rig.c.post("/api/actuators/sim_pump/command", json={"state": "on"})
    assert r.status_code == 409 and "dead-head" in r.json()["detail"]
    assert rig.c.post("/api/actuators/sim_valve_a/command", json={"state": "on", "duration_s": 60}).status_code == 200
    rig.step(1, 4)
    assert rig.c.post("/api/actuators/sim_pump/command", json={"state": "on", "duration_s": 30}).status_code == 200
    # closing the valve must also drop the pump
    rig.c.post("/api/actuators/sim_valve_a/command", json={"state": "off"})
    rig.step(1, 2)
    assert not rig.e.status(rig.t)["outputs"]["sim_pump"]["on"]


def test_emergency_stop_latches_blocks_and_persists(rig):
    rig.run_zone(duration=120)
    rig.step(1, 6)
    assert rig.c.post("/api/safety/estop").status_code == 200
    assert not any(v["on"] for v in rig.e.status(rig.t)["outputs"].values())
    assert rig.run_zone()[1] == "emergency stop is latched"
    assert rig.c.post("/api/actuators/sim_valve_a/command", json={"state": "on"}).status_code == 409
    rig.e.reload()  # as after a restart
    assert rig.e.estop is True
    assert rig.c.post("/api/safety/estop/reset", json={}).status_code == 422  # needs explicit confirmation
    assert rig.c.post("/api/safety/estop/reset", json={"confirm": True}).status_code == 200
    assert rig.run_zone(duration=5)[0]
    assert "emergency_stop" not in rig.alerts()


def test_startup_forces_all_outputs_off(rig):
    rig.plant.set("sim_valve_a", True)
    rig.plant.set("sim_pump", True)
    asyncio.run(rig.e.startup(rig.t))
    assert not rig.plant.states["sim_valve_a"] and not rig.plant.states["sim_pump"]


def test_driver_failure_on_switch_on_aborts_safely(rig, monkeypatch):
    real = SimulatedOutput.set

    async def broken(self, spec, on):
        if spec.id == "sim_pump" and on:
            raise RuntimeError("relay board offline")
        return await real(self, spec, on)

    monkeypatch.setattr(SimulatedOutput, "set", broken)
    rig.run_zone(duration=60)
    rig.step(1, 6)
    assert not any(v["on"] for v in rig.e.status(rig.t)["outputs"].values())
    assert "output_error" in rig.alerts()


def test_failed_off_command_is_retried_and_alerted(rig, monkeypatch):
    rig.run_zone(duration=60)
    rig.step(1, 6)
    real = SimulatedOutput.set
    state = {"fail": True}

    async def sticky(self, spec, on):
        if spec.id == "sim_pump" and not on and state["fail"]:
            raise RuntimeError("cannot reach relay")
        return await real(self, spec, on)

    monkeypatch.setattr(SimulatedOutput, "set", sticky)
    rig.e.stop_zone("soil_a", rig.t)
    rig.step(1, 3)
    assert "output_stuck" in rig.alerts() and rig.e.status(rig.t)["outputs"]["sim_pump"]["on"]
    state["fail"] = False
    rig.step(1, 2)
    assert not rig.e.status(rig.t)["outputs"]["sim_pump"]["on"] and "output_stuck" not in rig.alerts()


def test_leak_detection_when_idle(rig):
    s = rig.c.get("/api/irrigation/setup").json()["settings"]
    s.update(leak_sensor_id="sim_flow_main", leak_threshold_lpm=2, leak_confirm_s=5)
    assert rig.c.put("/api/irrigation/settings", json=s).status_code == 200
    rig.plant.leak_lpm = 6
    rig.step(1, 3)
    assert "leak_suspected" not in rig.alerts()
    rig.step(1, 5)
    assert "leak_suspected" in rig.alerts()


def test_simultaneous_zone_limit(rig):
    assert rig.run_zone("soil_a", 60)[0]
    ok, msg = rig.run_zone("hydro_1", 60)
    assert not ok and "simultaneous" in msg


# --------------------------------------------------------- automation/gate

def _open_gate(c):
    asyncio.run(c.app.state.ingest.poll_once())
    for cid in ("sensor_communication", "modbus_communication", "database_operation", "pump_protection",
                "water_level_interlock", "emergency_stop", "backup_restore"):
        assert c.post(f"/api/safety/checks/{cid}/run").json()["ok"], cid
    for cid in ("gpio_operation", "mqtt_communication", "actuator_feedback", "pump_protection", "water_level_interlock",
                "emergency_stop", "watchdog", "automatic_restart"):
        assert c.post(f"/api/safety/checks/{cid}/attest", json={"note": "tested on the bench, all good"}).status_code == 200
    return c.get("/api/safety").json()


def _local(y, mo, d, h, mi, s=0):
    return time.mktime((y, mo, d, h, mi, s, 0, 0, -1))


def _enable_auto(c, **zone_changes):
    z = next(z for z in c.get("/api/irrigation/setup").json()["zones"] if z["id"] == "soil_a")
    z.update(auto_enabled=True, min_interval_s=0, **zone_changes)
    assert c.put("/api/irrigation/zones/soil_a", json=z).status_code == 200
    g = c.get("/api/irrigation/setup").json()["settings"]
    g["auto_enabled"] = True
    assert c.put("/api/irrigation/settings", json=g).status_code == 200


def test_gate_is_closed_until_every_check_passes(client):
    s = client.get("/api/safety").json()
    assert s["production_automation_allowed"] is False and len(s["checks"]) == 14
    s = _open_gate(client)
    assert s["production_automation_allowed"] is True and all(c["passed"] for c in s["checks"])


def test_config_change_invalidates_commissioning(client):
    _open_gate(client)
    a = next(x for x in client.get("/api/irrigation/setup").json()["actuators"] if x["id"] == "sim_valve_a")
    a["max_runtime_s"] = 900
    client.put("/api/actuators/sim_valve_a", json=a)
    s = client.get("/api/safety").json()
    assert s["production_automation_allowed"] is False
    assert any(c["invalidated_by_config_change"] for c in s["checks"])


def test_attestation_needs_a_real_note_and_applicable_check(client):
    assert client.post("/api/safety/checks/watchdog/attest", json={"note": "ok"}).status_code == 422
    assert client.post("/api/safety/checks/database_operation/attest", json={"note": "this is a long enough note"}).status_code == 422
    assert client.post("/api/safety/checks/database_operation/run").json()["ok"] is True
    assert client.post("/api/safety/checks/watchdog/run").status_code == 422  # no auto test


def test_schedule_blocked_while_gate_closed_then_runs(client):
    r = Rig(client)
    r.feed()
    asyncio.run(client.app.state.engine.startup(T0))
    _enable_auto(client, schedule=[{"days": [0, 1, 2, 3, 4, 5, 6], "time": "06:00", "duration_s": 10}])
    r.t = _local(2026, 11, 2, 6, 0, 5)
    r.feed()
    asyncio.run(r.e.tick(r.t))
    assert not r.e.jobs and not r.e.auto_allowed()[0]
    _open_gate(client)
    r.feed()
    asyncio.run(r.e.tick(r.t + 1))  # inside the 2-minute window, gate now open
    assert "soil_a" in r.e.jobs and r.e.jobs["soil_a"].source == "schedule"
    # once per day only
    r.step(1, 30)
    r.t = _local(2026, 11, 2, 6, 1, 0)
    r.feed()
    asyncio.run(r.e.tick(r.t))
    assert "soil_a" not in r.e.jobs


def test_missed_schedule_window_is_skipped(client):
    r = Rig(client)
    r.feed()
    _enable_auto(client, schedule=[{"days": [0], "time": "06:00", "duration_s": 10}])
    _open_gate(client)
    r.t = _local(2026, 11, 2, 6, 10, 0)  # ten minutes late (e.g. after an outage): no catch-up
    r.feed()
    asyncio.run(r.e.tick(r.t))
    assert not r.e.jobs


def test_moisture_trigger_and_stale_sensor_blocks(client):
    r = Rig(client)
    r.feed()
    asyncio.run(client.app.state.engine.startup(T0))
    _enable_auto(client, moisture_sensor_ids=["soil_moist_1", "soil_moist_2"], moisture_start_below=30,
                 moisture_stop_at=40)
    _open_gate(client)
    r.t = T0 + 1000
    lat = client.app.state.ingest.latest
    r.feed()
    lat["soil_moist_1"] = LatestValue(20, int(r.t), 20)
    lat["soil_moist_2"] = LatestValue(25, int(r.t) - 500, 25)  # stale: must not decide
    asyncio.run(r.e.tick(r.t))
    assert not r.e.jobs
    lat["soil_moist_2"] = LatestValue(25, int(r.t), 25)
    asyncio.run(r.e.tick(r.t))
    assert r.e.jobs["soil_a"].source == "moisture"
    r.step(1, 6)
    for sid in ("soil_moist_1", "soil_moist_2"):
        lat[sid] = LatestValue(45, int(r.t), 45)
    r.step(1, 12)
    assert "soil_a" not in r.e.jobs
    assert client.get("/api/irrigation/history").json()["runs"][0]["end_reason"] == "moisture_reached"


def test_monitor_only_level_blocks_automation(client):
    _enable_auto(client)
    _open_gate(client)
    assert client.app.state.engine.auto_allowed()[0]
    cfg = client.get("/api/config").json()
    cfg["automation_level"] = "monitor_only"
    client.put("/api/config", json=cfg)
    assert "monitor only" in client.app.state.engine.auto_allowed()[1]


# ------------------------------------------------------- config validation

def test_validation_rules(client):
    base = {"id": "pump2", "name": "p", "kind": "pump", "driver": "simulated_output", "max_runtime_s": 100}
    assert client.post("/api/actuators", json={k: v for k, v in base.items() if k != "max_runtime_s"}).status_code == 422
    assert client.post("/api/actuators", json={**base, "max_runtime_s": 0}).status_code == 422
    assert client.post("/api/actuators", json=base).status_code == 201
    assert client.delete("/api/actuators/sim_pump").status_code == 409  # used by zones
    zone = {"id": "z9", "name": "z", "kind": "soil", "valve_id": "sim_valve_a", "pump_id": "pump2",
            "max_duration_s": 60, "default_duration_s": 30}
    assert client.post("/api/irrigation/zones", json=zone).status_code == 422          # pump without tank
    assert client.post("/api/irrigation/zones", json={**zone, "tank_id": "sim_tank", "valve_id": "sim_pump"}).status_code == 422
    assert client.post("/api/irrigation/zones", json={**zone, "tank_id": "sim_tank", "default_duration_s": 90}).status_code == 422
    bad_sched = {**zone, "tank_id": "sim_tank", "schedule": [{"days": [9], "time": "6:00", "duration_s": 5}]}
    assert client.post("/api/irrigation/zones", json=bad_sched).status_code == 422
    assert client.post("/api/irrigation/zones", json={**zone, "tank_id": "sim_tank", "min_flow_lpm": 5}).status_code == 422  # no flow sensor
    assert client.post("/api/irrigation/zones", json={**zone, "tank_id": "sim_tank"}).status_code == 201
    assert client.post("/api/irrigation/tanks", json={"id": "t2", "name": "t"}).status_code == 422  # no sensors
    assert client.post("/api/irrigation/tanks", json={"id": "t2", "name": "t", "level_sensor_id": "nope"}).status_code == 422


def test_gpio_output_validation_and_mixed_simulation_blocks_gate(client):
    gp = {"id": "gpio_valve", "name": "g", "kind": "valve", "driver": "gpio_output", "max_runtime_s": 60,
          "address": {"pin": 17}}
    assert client.post("/api/actuators", json={**gp, "address": {"pin": 3}}).status_code == 422  # I2C pin
    assert client.post("/api/actuators", json=gp).status_code == 201
    assert client.post("/api/actuators", json={**gp, "id": "gpio_valve2"}).status_code == 409   # same pin
    asyncio.run(client.app.state.ingest.poll_once())
    r = client.post("/api/safety/checks/sensor_communication/run").json()
    assert r["ok"] is False and "simulated" in r["detail"]  # simulated interlock sensors + real output


def test_clear_alert(client):
    from app.services import events
    events.raise_alert(client.app.state.db, "warning", "x", "y", "test")
    aid = client.get("/api/alerts").json()[0]["id"]
    assert client.post(f"/api/alerts/{aid}/clear").status_code == 200
    assert client.get("/api/alerts").json() == []


# ------------------------------------------------------ Modbus coil output

def test_modbus_coil_output_drives_fake_relay(settings):
    buses, transports = make_bus_manager({3: {}})
    ctx = HalContext(buses=buses)
    app = create_app(settings, ctx)
    with TestClient(app) as c:
        c.put("/api/hardware/buses", json=[{"id": "rs485_1", "port": "FAKE"}])
        body = {"id": "mb_valve", "name": "mb", "kind": "valve", "driver": "modbus_coil", "max_runtime_s": 60,
                "address": {"bus": "rs485_1", "slave": 3, "coil": 2, "active_high": False}}
        assert c.post("/api/actuators", json=body).status_code == 201
        assert c.post("/api/actuators", json={**body, "id": "dup"}).status_code == 409
        assert c.post("/api/actuators/mb_valve/command", json={"state": "on", "duration_s": 10}).status_code == 200
        t = transports[0]
        assert t.coils[(3, 2)] is False            # active-low: ON drives the coil low
        assert c.post("/api/actuators/mb_valve/command", json={"state": "off"}).status_code == 200
        assert t.coils[(3, 2)] is True
        assert c.post("/api/actuators/mb_valve/command", json={"state": "on"}).status_code == 200
        t.silent.add(3)                              # relay board stops answering
        r = c.post("/api/actuators/mb_valve/command", json={"state": "off"})
        assert r.status_code == 200
        asyncio.run(app.state.engine.tick(time.time()))
        assert app.state.engine.on.get("mb_valve") is not None  # still believed ON: failed OFF is not hidden
        assert "output_stuck" in [a["code"] for a in c.get("/api/alerts").json()]
