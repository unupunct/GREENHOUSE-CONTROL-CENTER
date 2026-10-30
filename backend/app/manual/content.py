"""Builds the manual's CONTENT from the live configuration (no generic filler).

Output is a list of sections; each section is a list of blocks:
  ("p", text) ("ul", [text]) ("ol", [text]) ("table", headers, rows) ("code", text) ("warn", text) ("h3", text) ("diagram", model)
Nothing here talks about equipment that has not been registered.
"""

from __future__ import annotations

import json
import time

from sqlalchemy import select

from app.core.models import (
    Actuator,
    ClimateRule,
    LightProgram,
    MaintenanceTask,
    Sensor,
    Tank,
    Window,
    Zone,
)
from app.planner import shopping, sizing, wiring
from app.services import commissioning, maintenance
from app.services.greenhouse_config import engineering_inputs, load_config

NEEDS_CAL = {"ph", "ec", "soil_moisture", "co2", "par"}


def _j(s):
    return json.loads(s or "{}")


def collect(app, tier: str | None = None, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    st, db = app.state, app.state.db
    cfg, opts = load_config(db), shopping.load_options(db)
    with db.session() as s:
        sensors = list(s.scalars(select(Sensor).order_by(Sensor.zone, Sensor.id)))
        acts = list(s.scalars(select(Actuator).order_by(Actuator.id)))
        zones, tanks, wins = (list(s.scalars(select(m))) for m in (Zone, Tank, Window))
        lights = list(s.scalars(select(LightProgram)))
        rules = list(s.scalars(select(ClimateRule).order_by(ClimateRule.priority.desc())))
        tasks = list(s.scalars(select(MaintenanceTask)))
    shop = shopping.compute(db, cfg, opts, tier, True)
    buses = [b.model_dump() for b in st.ctx.buses.configs()]
    return {
        "generated_at": int(now), "cfg": cfg, "opts": opts, "tier": shop["tier"], "shop": shop, "sensors": sensors, "acts": acts,
        "zones": zones, "tanks": tanks, "windows": wins, "lights": lights, "rules": rules, "tasks": tasks, "buses": buses,
        "modbus": wiring.modbus_table(db), "gpio_user": wiring.load_gpio(db), "electrical": sizing.electrical(opts),
        "gate": commissioning.status(db, st.engine), "maint": [maintenance.task_dict(t, now) for t in tasks],
        "real_sensors": [x for x in sensors if not x.simulated and x.enabled], "real_acts": [a for a in acts if a.driver != "simulated_output" and a.enabled],
        "sim_sensors": [x for x in sensors if x.simulated], "sim_acts": [a for a in acts if a.driver == "simulated_output"],
        "plant": st.ctx.plant,
    }


def _addr(d: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in d.items()) or "-"


def sections(d: dict, kind: str = "manual") -> list[tuple[str, list]]:
    if kind == "checklist":
        return _checklist(d)
    cfg = d["cfg"]
    S: list[tuple[str, list]] = []
    real_s, real_a = d["real_sensors"], d["real_acts"]
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(d["generated_at"]))

    # 1 Overview
    blocks: list = [("p", f"Installation manual for '{cfg.name}', generated {when} from the configuration stored in the application ({d['tier']} configuration). "
                          "It describes the equipment registered NOW. Regenerate it after changing the configuration."),
                    ("warn", "Mains wiring must be installed by a qualified electrician. Never connect mains voltage to Raspberry Pi GPIO or to hobby relay boards. "
                             "Heater, pump and actuator protections must work independently of this software. Automatic control stays blocked until the commissioning checks pass.")]
    if d["sim_sensors"] or d["sim_acts"]:
        blocks.append(("warn", f"{len(d['sim_sensors'])} SIMULATED sensor(s) and {len(d['sim_acts'])} simulated output(s) are registered. They are marked 'SIMULATED' below: "
                               "delete or replace them before commissioning real equipment."))
    if not real_s and not real_a:
        blocks.append(("p", "No real (non-simulated) sensors or outputs are registered yet, so there are no connection details to document. "
                            "Use the Hardware page to register real devices and generate this manual again. The equipment list below shows what the plan says you need."))
    S.append(("1. Overview and safety", blocks))

    # 2 Greenhouse
    miss = [i for i in engineering_inputs(cfg) if not i.provided]
    rows = [["Dimensions", f"{cfg.length_m:g} m x {cfg.width_m:g} m ({cfg.area_m2:g} m²)"], ["Growing methods", ", ".join(m.value for m in cfg.growing_methods)],
            ["Automation level", cfg.automation_level.value], ["Height / ridge", f"{cfg.height_m or 'not provided'} / {cfg.ridge_height_m or 'not provided'} m"],
            ["Covering", cfg.construction or "not provided"], ["Orientation", cfg.orientation.value if cfg.orientation else "not provided"],
            ["Electricity supply", cfg.electricity_supply.value if cfg.electricity_supply else "not provided"],
            ["Water pressure", f"{cfg.water_pressure_bar} bar" if cfg.water_pressure_bar is not None else "not provided"]]
    b2: list = [("table", ["Item", "Value"], rows)]
    if miss:
        b2.append(("warn", "Not provided (so dependent calculations are not final): " + "; ".join(f"{i.label} ({', '.join(i.needed_for)})" for i in miss)))
    S.append(("2. Greenhouse configuration", b2))

    # 3 Equipment list
    lines = d["shop"]["lines"]
    S.append(("3. Equipment list", [
        ("p", f"{len(lines)} lines for the {d['tier']} configuration. Quantity '?' means it cannot be calculated until the listed inputs are provided. "
              "Prices appear only where a supplier offer was recorded; nothing is estimated by the application."),
        ("table", ["Item", "Qty", "Basis / still needed", "Price", "Bought"],
         [[ln["name"], "?" if ln["qty"] is None else ln["qty"], ln["qty_basis"] + (f" [needs: {', '.join(ln['qty_missing'])}]" if ln["qty_missing"] else ""),
           f"{ln['unit_price_ron']:.2f} RON ({'verified' if ln['price_status'] == 'verified' else 'your estimate'})" if ln["unit_price_ron"] is not None else "no price recorded",
           "yes" if ln["purchased"] else ""] for ln in lines]),
        ("p", f"Total of priced lines: {d['shop']['budget']['grand_total_ron']:.2f} RON; {d['shop']['budget']['unpriced_lines']} line(s) have no recorded price.")]))

    # 4 Assembly
    S.append(("4. Assembly sequence", _assembly(d)))

    # 5 Connection details
    S.append(("5. Connection tables", _connections(d)))

    # 6 Power
    e = d["electrical"]
    p6: list = []
    if e["status"] == "needs_input":
        p6.append(("p", "No electrical loads were entered in the Planner, so the 24 V supply size and fuse ratings cannot be stated. Enter the loads on the Planner page."))
    else:
        p6.append(("table", ["Quantity", "Value"], [["Loads entered", e["loads"]], ["24 V DC supply (loads + headroom)", f"at least {e.get('psu_24v_min_w', 0):.0f} W" if e.get("psu_24v_min_w") else "no 24 V loads"],
                                                    ["Mains loads (listed for the electrician)", ", ".join(f"{k} {v:g} W" for k, v in e["totals_w"].items() if k == "230VAC") or "none"]]))
        if e.get("dc_fuse_suggestions"):
            p6.append(("table", ["24 V load", "Current A", "Suggested fuse (conceptual)"], [[f["load"], f["current_a"], f"{f['suggested_fuse_a']} A"] for f in e["dc_fuse_suggestions"]]))
    p6.append(("warn", e.get("safety", "Conceptual values: protective devices are selected and installed by a qualified person.")))
    S.append(("6. Power distribution and protection", p6))

    # 7 Software
    S.append(("7. Software installation and configuration", [
        ("ol", ["Prepare the Raspberry Pi (RASPBERRY_PI_SETUP.md).", "Install the service (INSTALLATION.md).", "Start with simulation off: GCC_SIMULATE=false on a fresh database.",
                "Register buses, sensors, outputs, tanks and zones to match section 5 (the application already holds the configuration this manual was generated from)."]),
        ("code", "sudo ./deploy/install.sh\nsystemctl status greenhouse\njournalctl -u greenhouse -n 50"),
        ("p", "Keep the interface on a private network: it has no login yet.")]))

    # 8 Calibration
    cal = [x for x in real_s if x.kind in NEEDS_CAL]
    S.append(("8. Calibration", [("table", ["Sensor", "Kind", "Calibration now", "Method"],
        [[x.id, x.kind, "none recorded" if x.calibrated_at is None else f"{x.cal_gain:.4f} x raw + {x.cal_offset:.4f}",
          {"ph": "pH 7.00 and 4.01 buffers, two-point", "ec": "EC standard solution", "soil_moisture": "wet/dry samples of your own soil", "co2": "fresh outdoor air",
           "par": "reference quantum sensor"}[x.kind]] for x in cal]) if cal else ("p", "No registered real sensors need a documented calibration. Temperature and humidity sensors are best checked against a reference (CALIBRATION_GUIDE.md).")]))

    # 9 Commissioning
    chk = [c for c in d["gate"]["checks"] if c["applicable"]]
    S.append(("9. Safety checks and commissioning", [
        ("p", f"{sum(c['passed'] for c in chk)} of {len(chk)} applicable checks passed. Automatic control is {'ALLOWED' if d['gate']['production_automation_allowed'] else 'BLOCKED'} ({d['gate']['reason']})."),
        ("table", ["Check", "Status", "What to do"], [[c["title"], "passed" if c["passed"] else "NOT passed", c["instructions"]] for c in chk])]))

    # 10 Maintenance
    S.append(("10. Maintenance schedule", [("table", ["Task", "Every (days)", "Next due"],
        [[t["title"], t["interval_days"], time.strftime("%Y-%m-%d", time.localtime(t["next_due_ts"])) + (" (OVERDUE)" if t["status"] == "overdue" else "")] for t in d["maint"]])
        if d["maint"] else ("p", "No maintenance tasks scheduled yet: create them from your equipment on the Maintenance page.")]))
    S.append(("11. If something does not work", [("ul", ["Hardware page → Test a sensor and read the message; Maintenance → Diagnostics explains messages in plain English.",
                                                         "TROUBLESHOOTING.md, MODBUS_SETUP.md, IRRIGATION_GUIDE.md, VENTILATION_GUIDE.md.",
                                                         "If in doubt, press the hardware emergency stop and find the cause before restarting."])]))
    return S


def _assembly(d: dict) -> list:
    real_s, real_a = d["real_sensors"], d["real_acts"]
    steps: list[str] = []
    if not real_s and not real_a:
        return [("p", "Nothing to assemble yet: no real equipment is registered. Register devices first, then regenerate.")]
    steps.append("Choose the cabinet position (IP65/IP66, upright, accessible, dry) and mount the DIN rail.")
    if real_a:
        steps.append("Have the qualified electrician install the mains supply, RCD/breakers, surge protection, earthing and the hardware emergency stop. Test them before connecting any equipment.")
        dc = [a for a in real_a if a.kind in ("valve", "motor", "dosing")]
        steps.append("Install the 24 V DC supply and a fuse or breaker for every DC feeder" + (f" ({len(dc)} DC output(s) registered)." if dc else "."))
    steps.append("Install the Raspberry Pi with its supply, cooling and storage; connect Ethernet; do not connect field wiring yet.")
    for b in d["buses"]:
        on = [m for m in d["modbus"] if m["bus"] == b["id"]]
        coils = [a for a in real_a if a.driver == "modbus_coil" and _j(a.address).get("bus") == b["id"]]
        steps.append(f"RS485 bus '{b['id']}' ({b['port']}, {b['baudrate']} baud, parity {b['parity']}, {b['stopbits']} stop bit): daisy-chain A/B twisted pair through {len(on)} sensor device-register(s)"
                     f"{' and ' + str(len(coils)) + ' relay coil(s)' if coils else ''}; 120 ohm termination at the two physical ends only, one bias point, shield earthed at one end, unique slave addresses.")
    i2c = [x for x in real_s if x.driver == "sht3x"]
    if i2c:
        steps.append(f"I2C: connect {len(i2c)} SHT3x row(s) to SDA GPIO2 (pin 3) / SCL GPIO3 (pin 5) with 3.3 V and ground; keep cables short (tens of centimetres).")
    w1 = [x for x in real_s if x.driver == "ds18b20"]
    if w1:
        steps.append(f"1-Wire: connect {len(w1)} DS18B20 probe(s) to GPIO4 (pin 7) with a 4.7 kΩ pull-up to 3.3 V and enable the w1-gpio overlay.")
    gp = [a for a in real_a if a.driver == "gpio_output"]
    if gp:
        steps.append("GPIO outputs: " + "; ".join(f"BCM {_j(a.address).get('pin')} -> {a.id}" for a in gp) + ". Each goes to an ISOLATED driver module, never directly to a load.")
    for t in d["tanks"]:
        if t.float_sensor_id:
            steps.append(f"Tank '{t.name}': fit the float switch and ALSO wire a hardware float switch (or equivalent) in series with the pump control circuit.")
    for a in real_a:
        if a.kind in ("heater", "co2"):
            steps.append(f"'{a.id}' ({a.kind}): fit an independent hardware protection (over-temperature cut-out / CO2 shut-off and room alarm) before first use.")
    for w in d["windows"]:
        steps.append(f"Window '{w.name}': motors on '{w.open_output_id}' (open) and '{w.close_output_id}' (close), travel {w.travel_time_s:g} s; fit end limit switches; never energise both directions together.")
    steps.append("Register every device in the application (section 5), then Test each sensor and switch each output manually with the greenhouse supervised.")
    steps.append("Calibrate sensors (section 8), complete the commissioning checks (section 9), only then enable automatic control.")
    return [("ol", steps)]


def _connections(d: dict) -> list:
    out: list = []
    real_s, real_a = d["real_sensors"], d["real_acts"]
    if d["sim_sensors"] or d["sim_acts"]:
        out.append(("p", f"SIMULATED (not real hardware, no wiring): sensors {', '.join(x.id for x in d['sim_sensors'][:12])}{'...' if len(d['sim_sensors']) > 12 else ''}; outputs {', '.join(a.id for a in d['sim_acts'])}."))
    if real_s:
        out.append(("h3", "Sensors"))
        out.append(("table", ["ID", "Name", "Zone", "Measures", "Driver / protocol", "Address", "Valid range", "Calibration"],
                    [[x.id, x.name, x.zone, f"{x.kind} ({x.unit})", f"{x.driver} / {x.protocol}", _addr(_j(x.address)),
                      f"{x.min_valid}..{x.max_valid}" if x.min_valid is not None else "-",
                      "none" if x.calibrated_at is None else f"{x.cal_gain:.4f}x{x.cal_offset:+.4f}"] for x in real_s]))
    if d["modbus"]:
        out.append(("h3", "Modbus addresses"))
        out.append(("table", ["Bus", "Slave", "Function", "Register", "Type", "Sensor"], [[m["bus"], m["slave"], m["function"], m["register"], m["datatype"], m["sensor_id"]] for m in d["modbus"]]))
        out.append(("p", "Registers are 0-based protocol addresses taken from each device's datasheet."))
    if d["buses"]:
        out.append(("h3", "RS485 buses"))
        out.append(("table", ["Bus", "Port", "Baud", "Parity", "Stop bits", "Timeout s"], [[b["id"], b["port"], b["baudrate"], b["parity"], b["stopbits"], b["timeout_s"]] for b in d["buses"]]))
    gpio_rows = [[p["bcm"], p["pin"], p["function"], p["used_by"]] for p in wiring.PI_FIXED_PINS
                 if (p["bcm"] in (2, 3) and any(x.driver == "sht3x" for x in real_s)) or (p["bcm"] == 4 and any(x.driver == "ds18b20" for x in real_s))]
    gpio_rows += [[a["bcm"], "", a["function"], a.get("device", "")] for a in d["gpio_user"]]
    gpio_rows += [[_j(a.address).get("pin"), "", f"output {a.id}", f"{a.kind}, {'active high' if _j(a.address).get('active_high', True) else 'active low'}"]
                  for a in real_a if a.driver == "gpio_output"]
    gpio_rows += [[_j(x.address).get("pin"), "", f"input {x.id}", "float/limit switch"] for x in real_s if x.driver == "gpio_input"]
    if gpio_rows:
        out.append(("h3", "Raspberry Pi GPIO (BCM numbers)"))
        out.append(("table", ["BCM", "Header pin", "Function", "Used by"], gpio_rows))
    if real_a:
        out.append(("h3", "Outputs"))
        out.append(("table", ["ID", "Kind", "Driver", "Address", "Max runtime", "Interlocks"],
                    [[a.id, a.kind, a.driver, _addr(_j(a.address)), f"{a.max_runtime_s}s", json.dumps(_j(a.interlocks)) if _j(a.interlocks) else "-"] for a in real_a]))
    if d["zones"] and real_a:
        out.append(("h3", "Irrigation zones and tanks"))
        out.append(("table", ["Zone", "Kind", "Valve", "Pump", "Tank", "Flow sensor", "Max duration"],
                    [[z.id, z.kind, z.valve_id, z.pump_id or "-", z.tank_id or "-", z.flow_sensor_id or "-", f"{z.max_duration_s}s"] for z in d["zones"]]))
        out.append(("table", ["Tank", "Level sensor", "Float sensor", "Minimum level"], [[t.id, t.level_sensor_id or "-", t.float_sensor_id or "-", f"{t.min_level_pct:g}%"] for t in d["tanks"]]))
    if d["windows"]:
        out.append(("h3", "Windows and screens"))
        out.append(("table", ["Window", "Open output", "Close output", "Travel s", "Limit switches", "Rain / wind sensors"],
                    [[w.id, w.open_output_id, w.close_output_id, w.travel_time_s, f"{w.open_limit_sensor_id or '-'} / {w.closed_limit_sensor_id or '-'}", f"{w.rain_sensor_id or '-'} / {w.wind_sensor_id or '-'} (max {w.wind_max_ms or '-'} m/s)"] for w in d["windows"]]))
    if d["lights"]:
        out.append(("h3", "Lighting programs"))
        out.append(("table", ["Program", "Outputs", "Mode", "Start", "Hours", "PAR sensor"], [[lp.id, ", ".join(json.loads(lp.output_ids)), lp.mode, lp.start_time, lp.photoperiod_h, lp.ppfd_sensor_id or "-"] for lp in d["lights"]]))
    if d["rules"]:
        out.append(("h3", "Climate rules"))
        out.append(("table", ["Rule", "Priority", "Conditions", "Actions"], [[r.id, r.priority, f"{len(json.loads(r.conditions))} ({r.match})", f"{len(json.loads(r.actions))}"] for r in d["rules"]]))
    if not out:
        out.append(("p", "No connection details yet: register real sensors and outputs first."))
    out.append(("diagram", d))
    return out


def _checklist(d: dict) -> list[tuple[str, list]]:
    S: list[tuple[str, list]] = []
    lines = [ln for ln in d["shop"]["lines"] if ln["group"] in ("essential", "recommended", "optional", "spare", "installation", "tool", "consumable")]
    S.append(("Components", [("p", "Tick each step as it is completed. 'Qty ?' means the quantity is not calculated yet."),
                             ("table", ["Component", "Qty", "Bought", "Mounted", "Wired", "Tested"], [[ln["name"], "?" if ln["qty"] is None else ln["qty"], "[x]" if ln["purchased"] else "[ ]", "[ ]", "[ ]", "[ ]"] for ln in lines])]))
    dev = []
    for x in d["real_sensors"]:
        dev.append([f"sensor {x.id}", f"{x.driver} {_addr(_j(x.address))}", "[ ]", "[ ]", "[ ]", "[ ]" if x.kind in NEEDS_CAL else "n/a"])
    for a in d["real_acts"]:
        dev.append([f"output {a.id} ({a.kind})", f"{a.driver} {_addr(_j(a.address))}", "[ ]", "[ ]", "[ ]", "n/a"])
    S.append(("Registered devices", [("table", ["Device", "Address", "Wired", "Registered", "Tested", "Calibrated"], dev)] if dev else
              [("p", "No real devices registered yet.")]))
    chk = [c for c in d["gate"]["checks"] if c["applicable"]]
    S.append(("Commissioning", [("table", ["Check", "Done", "What to test"], [[c["title"], "[x]" if c["passed"] else "[ ]", c["instructions"]] for c in chk])]))
    S.append(("Sign-off", [("table", ["Role", "Name", "Date", "Signature"], [["Installer", "", "", ""], ["Qualified electrician (mains)", "", "", ""], ["Owner", "", "", ""]])]))
    return S

