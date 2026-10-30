"""Wiring designer: Mermaid diagrams and tables derived from the real registry.

Diagrams are CONCEPTUAL. They show what connects to what, not pin-level wiring
of any specific product (that comes from the device datasheet). Pin tables
contain only the Raspberry Pi facts for interfaces this application uses, plus
whatever the user assigns.
"""

from __future__ import annotations

import json
from collections import defaultdict

from sqlalchemy import select

from app.core.db import Database
from app.core.models import AppSetting, Sensor
from app.planner import sizing
from app.planner.options import PlannerOptions
from app.services.greenhouse_config import GreenhouseConfig

GPIO_KEY = "gpio_assignments"

# Standard Raspberry Pi 40-pin header facts for the interfaces used here.
PI_FIXED_PINS = [
    {"function": "I2C1 SDA", "bcm": 2, "pin": 3, "used_by": "I2C sensors (e.g. SHT3x)"},
    {"function": "I2C1 SCL", "bcm": 3, "pin": 5, "used_by": "I2C sensors (e.g. SHT3x)"},
    {"function": "1-Wire (w1-gpio default)", "bcm": 4, "pin": 7, "used_by": "DS18B20 probes, 4.7 kΩ pull-up to 3.3 V"},
]
RESERVED_BCM = {2: "I2C1 SDA", 3: "I2C1 SCL", 4: "1-Wire (default)"}


def _mm(text: str) -> str:
    return text.replace('"', "'")


def architecture(cfg: GreenhouseConfig, o: PlannerOptions, sensors: list[Sensor]) -> str:
    by_proto: dict[str, int] = defaultdict(int)
    for s in sensors:
        by_proto[s.protocol] += 1
    irr = sizing.irrigation(cfg, o)
    lines = ["flowchart TB",
             '  subgraph CTRL["Central control - Raspberry Pi"]',
             '    PI["Raspberry Pi<br/>FastAPI + SQLite"]',
             '    WD["Hardware watchdog"]', '    DB[("Database")]',
             "    PI --- WD", "    PI --- DB", "  end",
             '  NET["Ethernet / Wi-Fi<br/>Browser UI"] --- PI',
             '  PI -- "USB" --> RS["USB-RS485 adapter"]',
             '  PI -- "I2C / 1-Wire" --> LOC["Local sensors<br/>(short cables)"]',
             '  PI -- "GPIO via isolation" --> DRV["DC driver / relay modules"]']
    if o.esp32_nodes:
        lines += ['  PI -. "MQTT: planned, NOT supported yet" .-> ESP["ESP32 nodes x%d"]' % o.esp32_nodes,
                  '  ESP --> ESS["Remote sensors"]']
    lines += ['  RS -- "A/B twisted pair, daisy chain" --> MB["Modbus RTU sensors<br/>%d registered"]' % by_proto.get("RS485", 0),
              '  LOC --> L1["I2C: %d, 1-Wire: %d registered"]' % (by_proto.get("I2C", 0), by_proto.get("1-Wire", 0)),
              '  DRV --> OUT["Outputs"]',
              '  OUT --> O1["Irrigation valves x%d"]' % (irr["soil_zones"] + irr["hydro_zones"]),
              '  OUT --> O2["Pumps"]', '  OUT --> O3["Fans / vent actuators"]',
              '  OUT --> O4["Lighting / heating via contactors<br/>(electrician)"]',
              '  OUT --> O5["Fertigation dosing"]']
    return "\n".join(lines)


def power(cfg: GreenhouseConfig, o: PlannerOptions) -> str:
    ele = sizing.electrical(o)
    psu = ele.get("psu_24v_min_w")
    psu_txt = f"24 V DC supply (>= {psu:.0f} W)" if psu else "24 V DC supply (rating needs load list)"
    return "\n".join([
        "flowchart LR",
        '  subgraph MAINS["Mains side - qualified electrician only"]',
        '    GRID["230 V / 400 V supply"] --> RCD["MCB + RCD + surge protection"]',
        '    RCD --> E["Emergency stop (cuts actuator power)"]',
        '    RCD --> PIPSU["Pi power supply"]', "  end",
        '  PIPSU --> UPS["DC UPS / shutdown module"] --> PI["Raspberry Pi"]',
        f'  E --> PSU["{psu_txt}"]',
        '  PSU --> F["Fuse / breaker per feeder"]',
        '  F --> DRV["DC MOSFET drivers / relays"]',
        '  DRV --> VAL["Valves"]', '  DRV --> ACT["Vent actuators + limit switches"]',
        '  F --> SENS["RS485 sensors (if 24 V powered)"]',
        '  PI -. "logic signals only, isolated" .-> DRV',
        '  subgraph HW["Hardware protection - independent of software"]',
        '    FL["Float switch: pump dry-run"]', '    TH["Heater over-temperature cut-out"]',
        '    LS["Motor limit switches"]', "  end",
        '  FL -. "in series with pump circuit" .- DRV', '  TH -. "in series with heater circuit" .- DRV',
        '  LS -. "in actuator circuit" .- ACT'])


def rs485_topology(sensors: list[Sensor], buses: list[dict]) -> str:
    groups: dict[str, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
    for s in sensors:
        if s.driver != "modbus_rtu":
            continue
        a = json.loads(s.address or "{}")
        groups[a.get("bus", "?")][a.get("slave", 0)].append(s.id)
    lines = ["flowchart LR"]
    if not buses and not groups:
        lines.append('  N["No RS485 bus configured yet (Hardware page)"]')
        return "\n".join(lines)
    for b in buses or [{"id": k, "port": "?", "baudrate": 0} for k in groups]:
        bid = b["id"]
        lines.append(f'  subgraph {bid}["{bid}: {b["port"]} @ {b["baudrate"]} baud"]')
        lines.append(f'    M_{bid}["Master (USB-RS485)<br/>bias + 120 ohm termination at this end"]')
        prev = f"M_{bid}"
        slaves = sorted(groups.get(bid, {}))
        for sl in slaves:
            node = f"S_{bid}_{sl}"
            names = _mm(", ".join(groups[bid][sl]))
            lines.append(f'    {node}["Slave {sl}<br/>{names}"]')
            lines.append(f"    {prev} -- A/B --- {node}")
            prev = node
        if slaves:
            lines.append(f'    T_{bid}["120 ohm termination (last device)"]')
            lines.append(f"    {prev} --- T_{bid}")
        lines.append("  end")
    return "\n".join(lines)


def modbus_table(db: Database) -> list[dict]:
    with db.session() as s:
        rows = s.scalars(select(Sensor).where(Sensor.driver == "modbus_rtu")).all()
    by_slave: dict[tuple[str, int], int] = defaultdict(int)
    out = []
    for r in rows:
        a = json.loads(r.address or "{}")
        by_slave[(a.get("bus"), a.get("slave"))] += 1
        out.append({"sensor_id": r.id, "name": r.name, "bus": a.get("bus"), "slave": a.get("slave"),
                    "function": a.get("function"), "register": a.get("register"),
                    "datatype": a.get("datatype"), "kind": r.kind})
    for row in out:
        row["sensors_on_this_address"] = by_slave[(row["bus"], row["slave"])]
    return sorted(out, key=lambda r: (str(r["bus"]), r["slave"] or 0, r["register"] or 0))


def load_gpio(db: Database) -> list[dict]:
    with db.session() as s:
        row = s.get(AppSetting, GPIO_KEY)
        return json.loads(row.value) if row else []


def validate_gpio(rows: list[dict]) -> list[str]:
    errs, seen = [], {}
    for r in rows:
        bcm = r.get("bcm")
        if not isinstance(bcm, int) or not 2 <= bcm <= 27:
            errs.append(f"BCM {bcm!r}: must be an integer 2-27 (header GPIO)")
            continue
        if bcm in seen:
            errs.append(f"BCM {bcm} assigned twice ('{seen[bcm]}' and '{r.get('function')}')")
        seen[bcm] = r.get("function")
        if bcm in RESERVED_BCM and "w1" not in str(r.get("function", "")).lower():
            errs.append(f"BCM {bcm} is used by {RESERVED_BCM[bcm]} in this application")
        if not r.get("function"):
            errs.append(f"BCM {bcm}: function/device is required")
    return errs
