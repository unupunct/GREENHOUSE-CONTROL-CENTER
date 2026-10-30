"""State-driven setup wizard.

Step status comes from the real system wherever possible (registered sensors,
fresh readings, calibration, outputs, commissioning). A few steps are things only
a person can do (wiring, electrician sign-off); those are attested with a note.
"""

from __future__ import annotations

import json
import time

from sqlalchemy import select

from app.core.models import Actuator, AppSetting, MaintenanceTask, Sensor, Tank, Window, Zone
from app.planner import shopping
from app.services import commissioning, system_info
from app.services.greenhouse_config import engineering_inputs, load_config

KEY = "wizard_manual"
CALIBRATE_KINDS = {"ph", "ec", "soil_moisture", "co2", "par"}

PI_COMMANDS = [
    {"cmd": "ssh <your-user>@greenhouse.local", "explain": "Connect to the Pi from your computer (use its IP address if the name does not resolve)."},
    {"cmd": "sudo apt update && sudo apt full-upgrade -y", "explain": "Refresh the package list and install all updates."},
    {"cmd": "sudo reboot", "explain": "Apply kernel updates."},
    {"cmd": "sudo raspi-config nonint do_i2c 0", "explain": "Enable the I2C bus for sensors such as the SHT35 (skip if you use none)."},
    {"cmd": "sudo timedatectl set-timezone Europe/Bucharest && timedatectl", "explain": "Set the time zone to YOUR local one (list: timedatectl list-timezones) and confirm the clock is synchronised: schedules, daily light totals and reports use local time."},
    {"cmd": "echo 'dtoverlay=w1-gpio' | sudo tee -a /boot/firmware/config.txt", "explain": "Enable 1-Wire on GPIO4 for DS18B20 probes (skip if you use none), then reboot."},
]
INSTALL_COMMANDS = [
    {"cmd": "sudo apt install -y python3 python3-venv git i2c-tools", "explain": "Install Python, virtual environments and I2C test tools."},
    {"cmd": "sudo ./deploy/install.sh", "explain": "Install the application as a service that starts at boot (read the script first; it is not yet tested on a Pi)."},
    {"cmd": "systemctl status greenhouse", "explain": "Check that the service is running."},
    {"cmd": "journalctl -u greenhouse -n 50", "explain": "Read the latest log lines if something is wrong."},
]


def _manual(db) -> dict:
    with db.session() as s:
        row = s.get(AppSetting, KEY)
    return json.loads(row.value) if row else {}


def mark(db, step_id: str, note: str) -> None:
    if step_id not in MANUAL_STEPS:
        raise ValueError("this step is not confirmed by hand: its status comes from the system")
    if len(note.strip()) < 10:
        raise ValueError("describe what you did (at least 10 characters)")
    data = _manual(db)
    data[step_id] = {"ts": int(time.time()), "note": note.strip()}
    _save(db, data)


def unmark(db, step_id: str) -> None:
    data = _manual(db)
    data.pop(step_id, None)
    _save(db, data)


def _save(db, data: dict) -> None:
    with db.session() as s:
        row = s.get(AppSetting, KEY)
        payload = json.dumps(data)
        if row is None:
            s.add(AppSetting(key=KEY, value=payload, updated_at=int(time.time())))
        else:
            row.value, row.updated_at = payload, int(time.time())


MANUAL_STEPS = {"pi_prepare", "software_install", "wiring_checked", "electrician_signoff", "manual_generated"}


def build(app, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    st, db = app.state, app.state.db
    cfg = load_config(db)
    manual = _manual(db)
    sysinfo = system_info.collect(st.settings.data_dir)
    gate = commissioning.status(db, st.engine)
    with db.session() as s:
        sensors = list(s.scalars(select(Sensor).where(Sensor.enabled.is_(True))))
        acts = list(s.scalars(select(Actuator).where(Actuator.enabled.is_(True))))
        zones, tanks = list(s.scalars(select(Zone))), list(s.scalars(select(Tank)))
        wins = list(s.scalars(select(Window)))
        n_tasks = len(list(s.scalars(select(MaintenanceTask.id))))
    real_s = [x for x in sensors if not x.simulated]
    real_a = [a for a in acts if a.driver != "simulated_output"]
    latest = st.ingest.latest
    fresh = lambda x: x.id in latest and now - latest[x.id].ts <= max(3 * st.settings.poll_interval_s, 15)  # noqa: E731
    steps: list[dict] = []

    def add(id_, stage, title, status, detail, why, how=None, commands=None, link=None, questions=None):
        steps.append({"id": id_, "stage": stage, "title": title, "status": status, "detail": detail, "why": why, "how": how or [],
                      "commands": commands or [], "link": link, "questions": questions or [],
                      "manual": id_ in MANUAL_STEPS, "attested": manual.get(id_)})

    # --- Plan
    missing = [i for i in engineering_inputs(cfg) if not i.provided]
    add("greenhouse", "Plan", "Describe your greenhouse", "done" if not missing else "in_progress",
        "All engineering inputs are provided." if not missing else f"{len(missing)} input(s) still missing: {', '.join(i.label for i in missing)}.",
        "Fan sizing, heating, irrigation and electrical design depend on height, orientation, covering, water pressure and electricity supply. The application will not guess them.",
        ["Open the Greenhouse page and fill in the missing details."], link="config",
        questions=[{"label": i.label, "question": i.question, "needed_for": i.needed_for} for i in missing])
    opts = shopping.load_options(db)
    data = shopping.compute(db, cfg, opts, None, False)
    ess = [ln for ln in data["lines"] if ln["group"] == "essential" and ln["qty"]]
    bought = sum(1 for ln in ess if ln["purchased"])
    add("plan_hardware", "Plan", "Plan and buy the hardware", "done" if ess and bought == len(ess) else "in_progress" if bought else "todo",
        f"{bought} of {len(ess)} essential items ticked as purchased; {data['budget']['needs_input_lines']} quantities still need planner inputs.",
        "The Planner and Shopping pages size the equipment for your greenhouse and track what you have bought.",
        ["Fill in the Planner inputs.", "Record real prices as offers.", "Tick items as you buy them."], link="shopping")
    # --- Stage 1
    on_pi = sysinfo["is_raspberry_pi"]
    s1 = ("done" if manual.get("pi_prepare") or (on_pi and sysinfo["compatible"]) else "not_applicable" if not on_pi else "todo")
    add("pi_prepare", "1 Raspberry Pi", "Prepare the Raspberry Pi", s1,
        (f"Running on {sysinfo['pi_model']}; checks {'pass' if sysinfo['compatible'] else 'FAIL'}." if on_pi else
         "This computer is not a Raspberry Pi (development host). Confirm by hand when your Pi is ready."),
        "A stable OS, fixed address and updated packages avoid most later problems.",
        ["Flash Raspberry Pi OS 64-bit with Raspberry Pi Imager (set hostname, user, SSH).", "Prefer Ethernet and a DHCP reservation in your router.",
         "Details: RASPBERRY_PI_SETUP.md. Not yet walked through on hardware with this project."], PI_COMMANDS, "system")
    # --- Stage 2
    s2 = "done" if manual.get("software_install") or not st.settings.simulate else "todo"
    add("software_install", "2 Software", "Install the application", s2,
        "Simulation mode is OFF." if not st.settings.simulate else "Simulation mode is ON (demo data). Start with GCC_SIMULATE=false on a fresh database for a real installation, or confirm by hand.",
        "Running as a service gives automatic start at boot and restarts after failures.",
        ["Follow INSTALLATION.md.", "Keep the interface on a private network: there is no login yet.", "Make and test a backup."], INSTALL_COMMANDS, None)
    # --- Stage 3
    stale = [x.id for x in real_s if not fresh(x)]
    s3 = "todo" if not real_s else "in_progress" if stale else "done"
    add("sensors", "3 Sensors", "Register and test your real sensors", s3,
        "No real (non-simulated) sensors registered yet." if not real_s else
        f"{len(real_s) - len(stale)}/{len(real_s)} real sensors answering" + (f"; silent: {', '.join(stale)}" if stale else "") + ".",
        "Each sensor must be registered with its bus address and tested before anything relies on it.",
        ["Add buses and sensors on the Hardware page, then Test each one.", "SENSOR_GUIDE.md and MODBUS_SETUP.md explain wiring and register maps."], link="hardware")
    need_cal = [x for x in real_s if x.kind in CALIBRATE_KINDS]
    uncal = [x.id for x in need_cal if x.calibrated_at is None]
    add("calibration", "3 Sensors", "Calibrate sensors that need it", "not_applicable" if not need_cal else "done" if not uncal else "in_progress",
        "No pH/EC/soil/CO2/PAR sensors registered." if not need_cal else (f"Not calibrated yet: {', '.join(uncal)}." if uncal else "All have a calibration on record."),
        "pH, EC and soil probes are not accurate straight out of the box.", ["Use buffer solutions or a reference instrument; see CALIBRATION_GUIDE.md."], link="hardware")
    add("wiring_checked", "3 Sensors", "Check all wiring", "done" if manual.get("wiring_checked") else "todo",
        "Confirmed by you." if manual.get("wiring_checked") else "Not yet confirmed.",
        "Most field faults are wiring faults: wrong polarity, swapped RS485 A/B, missing pull-ups, loose terminals.",
        ["Check polarity and terminals against your installation manual.", "RS485: termination at both ends only, shield earthed at one end.", "Fuse every DC feeder."], link="manual")
    # --- Stage 4
    zone_issues = [z.id for z in zones if z.pump_id and not z.tank_id]
    s4 = "todo" if not real_a else "in_progress" if zone_issues else "done"
    add("outputs", "4 Outputs", "Register pumps, valves, fans, windows and lights", s4,
        "No real (non-simulated) outputs registered yet." if not real_a else
        f"{len(real_a)} real output(s), {len(zones)} zone(s), {len(tanks)} tank(s), {len(wins)} window(s)." + (f" Zones without a tank: {', '.join(zone_issues)}." if zone_issues else ""),
        "Outputs are only switched through interlocks and runtime limits you configure.",
        ["Irrigation page → Setup for pumps, valves, tanks and zones; Climate page → Setup for fans, heaters, windows and lighting.",
         "Every heater and CO2 output needs a software safety limit AND independent hardware protection."], link="irrigation")
    add("electrician_signoff", "4 Outputs", "Mains installation by a qualified electrician", "done" if manual.get("electrician_signoff") else "todo",
        "Signed off by you." if manual.get("electrician_signoff") else "Not yet confirmed.",
        "Mains wiring, RCD/breakers, earthing and contactors must be done by a qualified electrician.",
        ["Never connect mains to Raspberry Pi GPIO or hobby relay boards.", "SAFETY.md and WIRING_GUIDE.md."], link="wiring")
    # --- Stage 5
    applicable = [c for c in gate["checks"] if c["applicable"]]
    passed = sum(1 for c in applicable if c["passed"])
    s5 = "blocked" if not acts else "done" if gate["production_automation_allowed"] else "in_progress" if passed else "todo"
    add("commissioning", "5 Verification", "Pass the commissioning checks", s5,
        "No outputs configured yet." if not acts else f"{passed} of {len(applicable)} applicable checks passed. {gate['reason']}.",
        "Automatic control stays blocked until the safety checks have passed. Physical checks need you to perform and attest them.",
        ["Open Irrigation → Commissioning checklist; run software tests and attest the physical ones."], link="irrigation")
    auto_on = st.engine.cfg.g.auto_enabled or st.climate.cfg.g.auto_enabled
    add("automation", "5 Verification", "Switch on automatic control", "blocked" if not gate["production_automation_allowed"] else "done" if auto_on else "todo",
        "Waiting for commissioning." if not gate["production_automation_allowed"] else ("Automatic control is switched on." if auto_on else "Commissioning passed; automatic control is still off."),
        "Only enable automation once you have watched manual operation work.",
        ["Enable automatic irrigation and/or climate control on their pages."], link="climate")
    add("maintenance", "After", "Set up the maintenance schedule", "done" if n_tasks else "todo",
        f"{n_tasks} task(s) scheduled." if n_tasks else "No maintenance tasks yet.",
        "Probes drift, filters clog, safety devices must be tested periodically.", ["Use 'Create from my equipment' on the Maintenance page and adjust the intervals."], link="maintenance")
    add("manual_generated", "After", "Generate and keep your installation manual", "done" if manual.get("manual_generated") else "todo",
        "Confirmed by you." if manual.get("manual_generated") else "Generate the manual for your actual configuration and keep a printed copy with the cabinet.",
        "The manual lists your real equipment, addresses and checks.", ["Manual page → download PDF/HTML/Markdown and the printable checklist."], link="manual")
    counted = [s for s in steps if s["status"] != "not_applicable"]
    done = sum(1 for s in counted if s["status"] == "done")
    nxt = next((s for s in steps if s["status"] in ("todo", "in_progress", "blocked")), None)
    return {"steps": steps, "progress": {"done": done, "total": len(counted), "percent": round(100 * done / max(1, len(counted)))},
            "next": nxt["id"] if nxt else None}
