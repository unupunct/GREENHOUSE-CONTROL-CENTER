import asyncio
import time

import pytest

from app.hal.outputs import SimulatedOutput
from app.services.ingest import LatestValue

T0 = 1_800_000_000.0


def local(y, mo, d, h, mi, s=0):
    return time.mktime((y, mo, d, h, mi, s, 0, 0, -1))


class Rig:
    def __init__(self, client):
        self.c = client
        self.e = client.app.state.climate
        self.ingest = client.app.state.ingest
        self.plant = client.app.state.ctx.plant
        self.t = T0
        self.e.clock = lambda: self.t
        self.vals = {"gh_temp_1": 22.0, "gh_par_1": 0.0}
        self.stale: set[str] = set()

    def feed(self):
        for sid, v in self.vals.items():
            if sid not in self.stale:
                self.ingest.latest[sid] = LatestValue(v, int(self.t), v)

    def step(self, seconds=1, n=1):
        for _ in range(n):
            self.t += seconds
            self.feed()
            asyncio.run(self.e.tick(self.t))

    def at(self, t):
        self.t = t
        self.feed()
        asyncio.run(self.e.tick(self.t))

    def on(self, oid):
        return self.plant.states.get(oid, False)

    def alerts(self):
        return [a["code"] for a in self.c.get("/api/alerts").json()]


def add_sensor(c, sid, kind="other"):
    r = c.post("/api/sensors", json={"id": sid, "name": sid, "kind": kind, "zone": "greenhouse", "unit": "x",
                                     "driver": "simulated", "address": {}})
    assert r.status_code == 201, r.text


def add_out(c, oid, kind, runtime=3600, **il):
    r = c.post("/api/actuators", json={"id": oid, "name": oid, "kind": kind, "driver": "simulated_output",
                                       "max_runtime_s": runtime, "interlocks": il})
    assert r.status_code == 201, r.text


def open_gate(c):
    asyncio.run(c.app.state.ingest.poll_once())
    for cid in ("sensor_communication", "modbus_communication", "database_operation", "pump_protection",
                "water_level_interlock", "emergency_stop", "backup_restore"):
        assert c.post(f"/api/safety/checks/{cid}/run").json()["ok"], cid
    for chk in c.get("/api/safety").json()["checks"]:
        if chk["manual_required"] and chk["applicable"]:
            assert c.post(f"/api/safety/checks/{chk['id']}/attest", json={"note": "tested on the bench, fine"}).status_code == 200
    s = c.get("/api/safety").json()
    assert s["production_automation_allowed"], [x["id"] for x in s["checks"] if not x["passed"]]


def enable(c):
    assert c.put("/api/climate/settings", json={"auto_enabled": True, "sensor_max_age_s": 30}).status_code == 200


def rule(c, rid, conds, actions, **kw):
    r = c.post("/api/climate/rules", json={"id": rid, "name": rid, "conditions": conds, "actions": actions, **kw})
    assert r.status_code == 201, r.text


TEMP_LOW = {"type": "sensor", "sensors": ["gh_temp_1"], "op": "<", "on": 18, "off": 20}
TEMP_HIGH = {"type": "sensor", "sensors": ["gh_temp_1"], "op": ">", "on": 28, "off": 26}


@pytest.fixture
def rig(client):
    client.app.state.climate.reload()
    r = Rig(client)
    r.feed()
    return r


# ------------------------------------------------------------ safety rules

def test_heater_and_co2_must_have_a_software_safety_limit(client):
    body = {"id": "heat1", "name": "h", "kind": "heater", "driver": "simulated_output", "max_runtime_s": 600}
    assert client.post("/api/actuators", json=body).status_code == 422
    ok = {**body, "interlocks": {"stop_if": {"sensor_id": "gh_temp_1", "above": 35}}}
    assert client.post("/api/actuators", json=ok).status_code == 201
    assert client.post("/api/actuators", json={**body, "id": "co2a", "kind": "co2"}).status_code == 422
    bad = {**body, "id": "fan1", "kind": "fan", "interlocks": {"requires_on": ["ghost"]}}
    assert client.post("/api/actuators", json=bad).status_code == 422
    assert client.post("/api/actuators", json={**bad, "interlocks": {"nonsense": 1}}).status_code == 422
    assert client.post("/api/actuators", json={**body, "id": "v1", "kind": "valve", "interlocks": {"min_on_s": 5}}).status_code == 422


def test_rule_validation(client):
    add_out(client, "fan1", "fan")
    add_out(client, "mot1", "motor")
    base = {"id": "r1", "name": "r", "conditions": [TEMP_HIGH], "actions": [{"output_id": "fan1", "state": "on"}]}
    assert client.post("/api/climate/rules", json={**base, "conditions": [{**TEMP_HIGH, "off": 30}]}).status_code == 422  # wrong hysteresis
    assert client.post("/api/climate/rules", json={**base, "conditions": [{**TEMP_HIGH, "sensors": ["nope"]}]}).status_code == 422
    assert client.post("/api/climate/rules", json={**base, "actions": [{"output_id": "mot1", "state": "on"}]}).status_code == 422
    assert client.post("/api/climate/rules", json={**base, "actions": [{"window_id": "nowin", "position_pct": 50}]}).status_code == 422
    assert client.post("/api/climate/rules", json={**base, "conditions": []}).status_code == 422
    assert client.post("/api/climate/rules", json={**base, "priority": 100}).status_code == 422  # 100 is reserved for lighting
    assert client.post("/api/climate/rules", json=base).status_code == 201
    assert client.post("/api/climate/rules", json=base).status_code == 409
    assert client.delete("/api/actuators/fan1").status_code == 409  # used by a rule


# ----------------------------------------------------------------- rules

def test_rules_do_nothing_until_gate_open_and_switch_on(rig):
    c = rig.c
    add_out(c, "fan1", "fan")
    rule(c, "hot", [TEMP_HIGH], [{"output_id": "fan1", "state": "on"}])
    rig.vals["gh_temp_1"] = 35
    rig.step(1, 3)
    assert not rig.on("fan1") and "closed" not in rig.e.auto_allowed()[1] and not rig.e.auto_allowed()[0]
    open_gate(c)
    rig.step(1, 3)
    assert not rig.on("fan1") and "switched off" in rig.e.auto_allowed()[1]  # master switch still off
    enable(c)
    rig.step(1, 3)
    assert rig.on("fan1")


def test_heating_with_hysteresis_dependency_and_event(rig):
    c = rig.c
    add_out(c, "circ", "fan")
    add_out(c, "heat", "heater", requires_on=["circ"], stop_if={"sensor_id": "gh_temp_1", "above": 35})
    rule(c, "cold", [TEMP_LOW], [{"output_id": "heat", "state": "on"}, {"output_id": "circ", "state": "on"}],
         on_delay_s=5, notify=True)
    open_gate(c)
    enable(c)
    rig.vals["gh_temp_1"] = 17
    rig.step(1, 4)
    assert not rig.on("heat")                       # on-delay not elapsed
    rig.step(1, 3)
    assert rig.on("heat") and rig.on("circ")        # heater and its required fan start together
    assert "rule_notify" in rig.alerts()
    rig.vals["gh_temp_1"] = 19                      # inside the band: keeps heating
    rig.step(1, 5)
    assert rig.on("heat")
    rig.vals["gh_temp_1"] = 20.5                    # above the release value
    rig.step(1, 3)
    assert not rig.on("heat") and not rig.on("circ")
    assert any("Rule 'cold'" in e["message"] and "activated" in e["message"] for e in c.get("/api/events?limit=200").json())


def test_software_over_temperature_cutoff_and_stale_sensor(rig):
    c = rig.c
    add_out(c, "heat", "heater", stop_if={"sensor_id": "gh_temp_1", "above": 35})
    rule(c, "cold", [{"type": "time", "start": "00:00", "end": "00:00"}], [{"output_id": "heat", "state": "on"}])
    open_gate(c)
    enable(c)
    rig.step(1, 3)
    assert rig.on("heat")
    rig.vals["gh_temp_1"] = 40
    rig.step(1, 2)
    assert not rig.on("heat")                       # rule still true, safety limit wins
    rig.vals["gh_temp_1"] = 25
    rig.step(1, 2)
    assert rig.on("heat")
    rig.stale = {"gh_temp_1"}
    rig.step(1, 35)                                  # safety sensor stale beyond 30 s: heater off
    assert not rig.on("heat")


def test_stale_condition_sensor_never_switches_on_and_switches_off(rig):
    c = rig.c
    add_out(c, "fan1", "fan")
    rule(c, "hot", [TEMP_HIGH], [{"output_id": "fan1", "state": "on"}])
    open_gate(c)
    enable(c)
    rig.vals["gh_temp_1"] = 35
    rig.step(1, 3)
    assert rig.on("fan1")
    rig.stale = {"gh_temp_1"}
    rig.step(1, 35)
    assert not rig.on("fan1")


def test_priority_and_manual_override(rig):
    c = rig.c
    add_out(c, "fan1", "fan")
    rule(c, "hot", [TEMP_HIGH], [{"output_id": "fan1", "state": "on"}], priority=50)
    rule(c, "quiet", [{"type": "time", "start": "00:00", "end": "00:00"}], [{"output_id": "fan1", "state": "off"}], priority=70)
    open_gate(c)
    enable(c)
    rig.vals["gh_temp_1"] = 35
    rig.step(1, 3)
    assert not rig.on("fan1")                       # the higher-priority OFF rule wins
    assert c.post("/api/actuators/fan1/command", json={"state": "on", "duration_s": 20}).status_code == 200
    rig.step(1, 3)
    assert rig.on("fan1")                           # manual override beats rules
    rig.step(1, 25)
    assert not rig.on("fan1")                       # ...for its duration only
    c.post("/api/actuators/fan1/command", json={"state": "on", "duration_s": 600})
    rig.step(1, 2)
    c.post("/api/climate/outputs/fan1/release")
    rig.step(1, 2)
    assert not rig.on("fan1")


def test_manual_off_override_blocks_rules_until_released(rig):
    c = rig.c
    add_out(c, "fan1", "fan")
    rule(c, "hot", [TEMP_HIGH], [{"output_id": "fan1", "state": "on"}])
    open_gate(c)
    enable(c)
    rig.vals["gh_temp_1"] = 35
    rig.step(1, 3)
    assert rig.on("fan1")
    assert c.post("/api/actuators/fan1/command", json={"state": "off", "duration_s": 100}).status_code == 200
    rig.step(1, 3)
    assert not rig.on("fan1")
    c.post("/api/climate/outputs/fan1/release")
    rig.step(1, 3)
    assert rig.on("fan1")


def test_manual_on_refused_by_interlock(rig):
    c = rig.c
    add_out(c, "heat", "heater", stop_if={"sensor_id": "gh_temp_1", "above": 35})
    rig.vals["gh_temp_1"] = 40
    rig.feed()
    r = c.post("/api/actuators/heat/command", json={"state": "on"})
    assert r.status_code == 409 and "safety limit" in r.json()["detail"]


def test_runtime_ceiling_blocks_then_resumes(rig):
    c = rig.c
    add_out(c, "fan1", "fan", runtime=10)
    rule(c, "hot", [TEMP_HIGH], [{"output_id": "fan1", "state": "on"}])
    open_gate(c)
    enable(c)
    rig.vals["gh_temp_1"] = 35
    rig.step(1, 5)
    assert rig.on("fan1")
    rig.step(1, 8)                                   # beyond 10 s: forced off
    assert not rig.on("fan1") and "max_runtime" in rig.alerts()
    rig.step(1, 30)
    assert not rig.on("fan1")                        # cooling-down period (>= 60 s)
    rig.step(1, 35)                                  # t=78: the block ended at ~72, fan is running again
    assert rig.on("fan1")


def test_min_on_and_min_off_protect_equipment(rig):
    c = rig.c
    add_out(c, "cool", "cooler", min_on_s=20, min_off_s=30)
    rule(c, "hot", [TEMP_HIGH], [{"output_id": "cool", "state": "on"}])
    open_gate(c)
    enable(c)
    rig.vals["gh_temp_1"] = 35
    rig.step(1, 3)
    assert rig.on("cool")
    rig.vals["gh_temp_1"] = 20                       # rule releases immediately...
    rig.step(1, 5)
    assert rig.on("cool")                            # ...but the output honours min-on
    rig.step(1, 20)
    assert not rig.on("cool")
    rig.vals["gh_temp_1"] = 35
    rig.step(1, 10)
    assert not rig.on("cool")                        # min-off not elapsed
    rig.step(1, 25)
    assert rig.on("cool")


def test_mutual_exclusion_heater_cooler(rig):
    c = rig.c
    add_out(c, "cool", "cooler")
    add_out(c, "heat", "heater", forbids_on=["cool"], stop_if={"sensor_id": "gh_temp_1", "above": 45})
    rule(c, "rule_a", [{"type": "time", "start": "00:00", "end": "00:00"}], [{"output_id": "cool", "state": "on"}], priority=60)
    rule(c, "rule_b", [{"type": "time", "start": "00:00", "end": "00:00"}], [{"output_id": "heat", "state": "on"}], priority=50)
    open_gate(c)
    enable(c)
    rig.step(1, 3)
    assert rig.on("cool") and not rig.on("heat")


def test_vpd_and_month_conditions(rig):
    c = rig.c
    add_sensor(c, "rh_a")
    add_out(c, "dehum", "dehumidifier")
    rule(c, "vpd_low", [{"type": "vpd", "temp_sensors": ["gh_temp_1"], "rh_sensors": ["rh_a"], "op": "<", "on": 0.4, "off": 0.6},
                        {"type": "month", "months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]}],
         [{"output_id": "dehum", "state": "on"}])
    open_gate(c)
    enable(c)
    rig.vals.update(gh_temp_1=20, rh_a=95)           # VPD about 0.12 kPa
    rig.step(1, 3)
    assert rig.on("dehum")
    rig.vals["rh_a"] = 60                            # VPD about 0.93 kPa
    rig.step(1, 3)
    assert not rig.on("dehum")


def test_estop_and_startup_force_everything_off(rig):
    c = rig.c
    add_out(c, "fan1", "fan")
    rule(c, "hot", [TEMP_HIGH], [{"output_id": "fan1", "state": "on"}])
    open_gate(c)
    enable(c)
    rig.vals["gh_temp_1"] = 35
    rig.step(1, 3)
    assert rig.on("fan1")
    assert c.post("/api/safety/estop").status_code == 200
    assert not rig.on("fan1")
    rig.step(1, 3)
    assert not rig.on("fan1") and c.post("/api/actuators/fan1/command", json={"state": "on"}).status_code == 409
    c.post("/api/safety/estop/reset", json={"confirm": True})
    rig.plant.set("fan1", True)                      # something left it on
    asyncio.run(rig.e.startup(rig.t))
    assert not rig.on("fan1")


def test_driver_failure_raises_alert_and_blocks_retry(rig, monkeypatch):
    c = rig.c
    add_out(c, "fan1", "fan")
    rule(c, "hot", [TEMP_HIGH], [{"output_id": "fan1", "state": "on"}])
    open_gate(c)
    enable(c)
    real = SimulatedOutput.set

    async def broken(self, spec, on):
        if spec.id == "fan1" and on:
            raise RuntimeError("contactor offline")
        return await real(self, spec, on)

    monkeypatch.setattr(SimulatedOutput, "set", broken)
    rig.vals["gh_temp_1"] = 35
    rig.step(1, 3)
    assert not rig.on("fan1") and "output_error" in rig.alerts()


# ----------------------------------------------------------------- windows

def add_window(c, travel=100, **extra):
    add_out(c, "w_open", "motor", runtime=300)
    add_out(c, "w_close", "motor", runtime=300)
    body = {"id": "win1", "name": "Vent", "open_output_id": "w_open", "close_output_id": "w_close",
            "travel_time_s": travel, "min_rest_s": 0, "min_step_pct": 2, **extra}
    r = c.post("/api/climate/windows", json=body)
    assert r.status_code == 201, r.text


def pos(rig):
    return next(w for w in rig.e.status(rig.t)["windows"] if w["id"] == "win1")


def test_window_validation(client):
    add_out(client, "mo", "motor", runtime=100)
    add_out(client, "mc", "motor", runtime=300)
    add_out(client, "fan1", "fan")
    base = {"id": "w1", "name": "w", "open_output_id": "mo", "close_output_id": "mc", "travel_time_s": 100}
    assert client.post("/api/climate/windows", json=base).status_code == 422                     # runtime < 1.2 x travel
    assert client.post("/api/climate/windows", json={**base, "travel_time_s": 60}).status_code == 201
    assert client.post("/api/climate/windows", json={**base, "id": "w2", "travel_time_s": 60}).status_code == 409  # outputs reused
    assert client.post("/api/climate/windows", json={**base, "id": "w3", "open_output_id": "mc"}).status_code == 422
    assert client.post("/api/climate/windows", json={**base, "id": "w3", "open_output_id": "fan1"}).status_code == 422
    assert client.post("/api/climate/windows", json={**base, "id": "w3", "wind_max_ms": 10}).status_code == 422


def test_window_homes_then_moves_and_never_energises_both(rig):
    c = rig.c
    add_window(c)
    open_gate(c)
    rig.feed()
    assert c.post("/api/climate/windows/win1/position", json={"position_pct": 40}).status_code == 200
    seen_both = False
    for _ in range(300):
        rig.step(1)
        seen_both |= rig.on("w_open") and rig.on("w_close")
        if pos(rig)["position_pct"] == 40 and not pos(rig)["moving"]:
            break
    assert not seen_both
    assert pos(rig)["position_pct"] == pytest.approx(40, abs=0.5) and not pos(rig)["moving"]
    assert not rig.on("w_open") and not rig.on("w_close")
    assert pos(rig)["position_is_estimate"] is True


def test_window_timing_open_then_close_with_overdrive(rig):
    c = rig.c
    add_window(c)
    open_gate(c)
    rig.e.win["win1"].pos = 0.0
    c.post("/api/climate/windows/win1/position", json={"position_pct": 50})
    rig.step(1, 2)
    assert rig.on("w_open")
    rig.step(1, 50)
    assert not rig.on("w_open") and pos(rig)["position_pct"] == 50
    c.post("/api/climate/windows/win1/position", json={"position_pct": 0})
    rig.step(1, 2)
    assert rig.on("w_close")
    rig.step(1, 70)                                  # 50% of 100 s + 10% overdrive
    assert not rig.on("w_close") and pos(rig)["position_pct"] == 0


def test_closed_limit_switch_stops_early(rig):
    c = rig.c
    add_sensor(c, "lim_closed")
    add_window(c, closed_limit_sensor_id="lim_closed")
    open_gate(c)
    rig.e.win["win1"].pos = 100.0
    rig.vals["lim_closed"] = 0.0
    c.post("/api/climate/windows/win1/position", json={"position_pct": 0})
    rig.step(1, 20)
    assert rig.on("w_close")
    rig.vals["lim_closed"] = 1.0
    rig.step(1, 2)
    assert not rig.on("w_close") and pos(rig)["position_pct"] == 0


def test_rain_and_wind_close_vent_and_fail_safe_on_stale_sensor(rig):
    c = rig.c
    add_sensor(c, "rain_1")
    add_sensor(c, "wind_1")
    add_window(c, rain_sensor_id="rain_1", wind_sensor_id="wind_1", wind_max_ms=10)
    rule(c, "hot", [TEMP_HIGH], [{"window_id": "win1", "position_pct": 100}])
    open_gate(c)
    enable(c)
    rig.vals.update(gh_temp_1=35, rain_1=0.0, wind_1=3.0)
    rig.e.win["win1"].pos = 0.0
    rig.step(1, 115)
    assert pos(rig)["position_pct"] == 100            # hot, no hazard: open
    rig.vals["wind_1"] = 15.0
    rig.step(1, 3)
    assert pos(rig)["hazard"] and "wind" in pos(rig)["hazard"] and rig.on("w_close")
    rig.step(1, 110)
    assert pos(rig)["position_pct"] == 0
    rig.vals["wind_1"] = 3.0
    rig.step(1, 115)
    assert pos(rig)["position_pct"] == 100
    rig.stale = {"rain_1"}
    rig.step(1, 40)                                   # rain sensor silent: close
    rig.step(1, 110)
    assert pos(rig)["position_pct"] == 0 and "rain sensor" in (pos(rig)["hazard"] or "")


def test_window_default_closed_when_no_rule_wants_it_open(rig):
    c = rig.c
    add_window(c)
    open_gate(c)
    enable(c)
    rig.e.win["win1"].pos = 60.0
    rig.step(1, 3)
    assert rig.on("w_close")                           # nobody asked for it open: close
    rig.step(1, 90)
    assert pos(rig)["position_pct"] == 0


def test_estop_stops_window_motor(rig):
    c = rig.c
    add_window(c)
    open_gate(c)
    rig.e.win["win1"].pos = 0.0
    c.post("/api/climate/windows/win1/position", json={"position_pct": 100})
    rig.step(1, 10)
    assert rig.on("w_open")
    c.post("/api/safety/estop")
    assert not rig.on("w_open")
    rig.step(1, 3)
    assert not rig.on("w_open") and not pos(rig)["moving"]


def test_motor_runtime_ceiling_makes_position_unknown(rig):
    c = rig.c
    add_out(c, "w_open", "motor", runtime=120)
    add_out(c, "w_close", "motor", runtime=120)
    assert c.post("/api/climate/windows", json={"id": "win1", "name": "v", "open_output_id": "w_open",
                                                "close_output_id": "w_close", "travel_time_s": 100, "min_rest_s": 0}).status_code == 201
    open_gate(c)
    rig.e.win["win1"].pos = 0.0
    c.post("/api/climate/windows/win1/position", json={"position_pct": 100})
    rig.e.cfg.windows["win1"]["travel_time_s"] = 500   # engine believes the stroke is longer than the ceiling
    rig.step(1, 125)
    assert not rig.on("w_open") and pos(rig)["position_pct"] is None and "max_runtime" in rig.alerts()


# ---------------------------------------------------------------- lighting

def add_light(c, **kw):
    add_out(c, "lamp", "light", runtime=90000)
    body = {"id": "lp1", "name": "Lights", "output_ids": ["lamp"], "start_time": "06:00", "photoperiod_h": 16, **kw}
    r = c.post("/api/climate/lights", json=body)
    assert r.status_code == 201, r.text


def test_photoperiod_schedule(rig):
    c = rig.c
    add_light(c)
    open_gate(c)
    enable(c)
    rig.at(local(2026, 11, 2, 5, 59))
    assert not rig.on("lamp")
    rig.at(local(2026, 11, 2, 6, 1))
    assert rig.on("lamp")
    rig.at(local(2026, 11, 2, 21, 59))
    assert rig.on("lamp")
    rig.at(local(2026, 11, 2, 22, 1))
    assert not rig.on("lamp")


def test_dli_mode_integrates_ppfd_and_stops_at_target(rig):
    c = rig.c
    add_sensor(c, "pwr_1")
    add_light(c, mode="dli", ppfd_sensor_id="gh_par_1", dli_target=0.3, on_below_ppfd=200, off_above_ppfd=400,
              power_sensor_id="pwr_1")
    open_gate(c)
    enable(c)
    base = local(2026, 11, 2, 8, 0)
    rig.vals.update(gh_par_1=100.0, pwr_1=0.0)       # dull day: lights wanted
    rig.at(base)
    rig.at(base + 1)
    assert rig.on("lamp")
    rig.vals.update(gh_par_1=300.0, pwr_1=1000.0)    # lights on, canopy PPFD 300 (inside the band: stay on)
    for k in range(2, 1300, 1):
        rig.at(base + k)
        if not rig.on("lamp"):
            break
    st = rig.e.status(rig.t)["lighting"]
    assert not rig.on("lamp") and 0.3 <= st["dli_mol"] < 0.32   # stopped as soon as 0.3 mol/m2 was reached
    assert st["light_kwh"] > 0
    rig.at(rig.t + 60)
    assert not rig.on("lamp")                          # stays off for the rest of the day


def test_dli_resets_the_next_day_and_persists(rig):
    c = rig.c
    add_light(c, mode="dli", ppfd_sensor_id="gh_par_1", dli_target=100, on_below_ppfd=200, off_above_ppfd=400)
    open_gate(c)
    day1 = local(2026, 11, 2, 12, 0)
    rig.vals["gh_par_1"] = 1000.0
    rig.at(day1)
    for k in range(1, 11):                           # 100 s in 10 s steps (long gaps are not integrated)
        rig.at(day1 + 10 * k)
    assert rig.e.status(rig.t)["lighting"]["dli_mol"] == pytest.approx(0.1, abs=0.001)
    rig.at(local(2026, 11, 3, 0, 5))
    assert rig.e.status(rig.t)["lighting"]["dli_mol"] < 0.01
    h = c.get("/api/climate/lighting/history").json()["days"]
    assert any(d["date"] == "2026-11-02" and d["dli_mol"] == pytest.approx(0.1, abs=0.001) for d in h)


def test_light_program_validation(client):
    add_out(client, "lamp", "light", runtime=3600)
    add_out(client, "fan1", "fan")
    base = {"id": "lp1", "name": "L", "output_ids": ["lamp"]}
    assert client.post("/api/climate/lights", json={**base, "mode": "dli"}).status_code == 422
    assert client.post("/api/climate/lights", json={**base, "mode": "dli", "ppfd_sensor_id": "gh_par_1", "dli_target": 10,
                                                    "on_below_ppfd": 400, "off_above_ppfd": 200}).status_code == 422
    assert client.post("/api/climate/lights", json={**base, "output_ids": ["fan1"]}).status_code == 422
    assert client.post("/api/climate/lights", json=base).status_code == 422          # lamp runtime (3600 s) < 16 h photoperiod
    client.delete("/api/actuators/lamp")
    add_out(client, "lamp", "light", runtime=90000)
    assert client.post("/api/climate/lights", json=base).status_code == 201
    assert client.post("/api/climate/lights", json={**base, "id": "lp2"}).status_code == 409  # output already used
    # an output in a lighting program cannot also be driven by a rule
    r = client.post("/api/climate/rules", json={"id": "r1", "name": "r", "conditions": [TEMP_HIGH],
                                                "actions": [{"output_id": "lamp", "state": "on"}]})
    assert r.status_code == 422


# --------------------------------------------------- template and gate

def test_setpoint_template_generates_rules_and_replaces_them(client):
    add_out(client, "circ", "fan")
    add_out(client, "exh", "fan")
    add_out(client, "heat", "heater", stop_if={"sensor_id": "gh_temp_1", "above": 40})
    add_out(client, "w_open", "motor", runtime=300)
    add_out(client, "w_close", "motor", runtime=300)
    client.post("/api/climate/windows", json={"id": "win1", "name": "v", "open_output_id": "w_open",
                                              "close_output_id": "w_close", "travel_time_s": 100})
    t = {"temp_sensors": ["gh_temp_1"], "day_start": "07:00", "night_start": "19:00", "heater_id": "heat",
         "circulation_fan_id": "circ", "day_heat_on_below": 16, "day_heat_off_above": 18,
         "night_heat_on_below": 12, "night_heat_off_above": 14, "vent_window_ids": ["win1"],
         "vent_open_above": 26, "vent_close_below": 24, "exhaust_fan_ids": ["exh"], "fan_on_above": 30, "fan_off_below": 28}
    r = client.post("/api/climate/templates/setpoints", json=t).json()
    assert set(r["rules"]) == {"tpl_heat_day", "tpl_heat_night", "tpl_vent", "tpl_fans"}
    rules = {x["id"]: x for x in client.get("/api/climate/setup").json()["rules"]}
    assert rules["tpl_heat_day"]["generated"] and rules["tpl_vent"]["conditions"][0]["off"] == 24
    t2 = {**t, "heater_id": None}
    assert set(client.post("/api/climate/templates/setpoints", json=t2).json()["rules"]) == {"tpl_vent", "tpl_fans"}
    assert "tpl_heat_day" not in {x["id"] for x in client.get("/api/climate/setup").json()["rules"]}
    bad = {"temp_sensors": ["gh_temp_1"], "day_start": "07:00", "night_start": "19:00"}
    assert client.post("/api/climate/templates/setpoints", json=bad).status_code == 422  # no setpoints: nothing invented
    bad_h = {**t, "vent_close_below": 30}
    assert client.post("/api/climate/templates/setpoints", json=bad_h).status_code == 422  # release above trigger


def test_new_checks_apply_only_when_relevant(client):
    ids = lambda: {c["id"]: c for c in client.get("/api/safety").json()["checks"]}  # noqa: E731
    assert not ids()["heater_protection"]["applicable"] and not ids()["window_limits"]["applicable"]
    add_out(client, "heat", "heater", stop_if={"sensor_id": "gh_temp_1", "above": 40})
    assert ids()["heater_protection"]["applicable"]
    open_gate_ok = True
    asyncio.run(client.app.state.ingest.poll_once())
    for cid in ("sensor_communication", "modbus_communication", "database_operation", "pump_protection",
                "water_level_interlock", "emergency_stop", "backup_restore"):
        client.post(f"/api/safety/checks/{cid}/run")
    for chk in client.get("/api/safety").json()["checks"]:
        if chk["manual_required"] and chk["applicable"] and chk["id"] != "heater_protection":
            client.post(f"/api/safety/checks/{chk['id']}/attest", json={"note": "tested on the bench, fine"})
    s = client.get("/api/safety").json()
    assert open_gate_ok and not s["production_automation_allowed"]
    assert [c["id"] for c in s["checks"] if not c["passed"]] == ["heater_protection"]
    client.post("/api/safety/checks/heater_protection/attest", json={"note": "cut-out tested with the Pi powered off"})
    assert client.get("/api/safety").json()["production_automation_allowed"]
