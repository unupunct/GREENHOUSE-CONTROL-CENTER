"""Bill of materials builder.

Catalogue entries are GENERIC requirements ("24 V DIN-rail supply, at least N W")
unless a real product is named. No price, URL, stock or delivery time lives here:
those come only from user-entered or researched *offers* (see ``Offer`` model).
Named models are listed only where the product is well known; their
specifications are not reproduced - read the manufacturer datasheet.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from app.planner import sizing
from app.planner.options import PlannerOptions
from app.services.greenhouse_config import GreenhouseConfig, GrowingMethod

TIER_ORDER = {"low": 0, "recommended": 1, "professional": 2}
SUBSYSTEMS = ["Controller", "Climate sensing", "Soil & hydroponic sensing", "Irrigation",
              "Ventilation & climate", "Lighting", "Electrical & safety",
              "Spares", "Consumables", "Tools", "Installation materials"]


@dataclass
class BomLine:
    id: str
    subsystem: str
    group: str            # essential | recommended | optional | spare | consumable | tool | installation
    min_tier: str         # smallest tier that includes it
    name: str
    spec: str
    qty: int | None       # None = cannot be calculated yet
    qty_basis: str
    qty_missing: list[str] = field(default_factory=list)
    manufacturer: str | None = None
    model: str | None = None
    alternatives: list[str] = field(default_factory=list)
    compat: str = ""
    search: str = ""      # search words for supplier look-ups

    def dict(self) -> dict:
        return asdict(self)


def _line(id_, sub, group, tier, name, spec, qty, basis="", **kw) -> BomLine:
    return BomLine(id_, sub, group, tier, name, spec, qty, basis, **kw)


def build_bom(cfg: GreenhouseConfig, o: PlannerOptions) -> list[BomLine]:
    ar = sizing.areas(cfg, o)
    st = sizing.climate_stations(cfg, o)
    irr = sizing.irrigation(cfg, o)
    vent = sizing.ventilation(cfg, o)
    lit = sizing.lighting(cfg, o)
    ele = sizing.electrical(o)
    soil = ar["soil_m2"] > 0
    hydro = GrowingMethod.HYDROPONIC in cfg.growing_methods
    soil_zones, hydro_zones = irr["soil_zones"], irr["hydro_zones"]
    zones = soil_zones + hydro_zones
    soil_probes = soil_zones * o.soil_probes_per_zone
    tanks = o.hydro_tanks if hydro else 0
    pump_count = (1 if soil else 0) + (1 if hydro else 0)
    dc_outputs = zones + (vent["fans"] or 0) + (o.vent_actuators or 0)
    B: list[BomLine] = []
    add = B.append

    # ---- Controller
    add(_line("pi5_4gb", "Controller", "essential", "low", "Raspberry Pi 5, 4 GB",
              "Central controller running this application", 1, "one controller",
              manufacturer="Raspberry Pi Ltd", model="Raspberry Pi 5 4GB",
              alternatives=["Raspberry Pi 4 Model B 4GB", "Raspberry Pi 5 8GB"],
              compat="Raspberry Pi OS 64-bit. Needs its own supply, case/cooler and storage.",
              search="Raspberry Pi 5 4GB"))
    add(_line("pi_psu", "Controller", "essential", "low", "Raspberry Pi USB-C power supply (official, for the chosen model)",
              "5 V USB-C; Pi 5: 5 V/5 A class", 1, "one controller", manufacturer="Raspberry Pi Ltd",
              search="Raspberry Pi 27W USB-C power supply"))
    add(_line("pi_cooler", "Controller", "recommended", "recommended", "Active cooler for Raspberry Pi 5",
              "Fan + heatsink", 1, "one controller", manufacturer="Raspberry Pi Ltd",
              search="Raspberry Pi 5 Active Cooler"))
    add(_line("storage_sd", "Controller", "essential", "low", "High-endurance microSD card, 32-64 GB",
              "Rated for continuous recording (dashcam/surveillance class)", 2,
              "1 in use + 1 prepared spare", search="high endurance microSD 64GB"))
    add(_line("storage_nvme", "Controller", "recommended", "recommended", "M.2 HAT + NVMe SSD (or USB SSD)",
              "Better write endurance than microSD", 1, "one controller",
              compat="Pi 5 only (PCIe). On Pi 4 use a USB-attached SSD.", search="Raspberry Pi M.2 HAT NVMe SSD"))
    add(_line("pi_enclosure", "Controller", "essential", "low", "Enclosure for the Raspberry Pi (IP65 if in the greenhouse)",
              "Ventilated or fanless depending on location", 1, "one controller", search="IP65 enclosure DIN rail"))
    add(_line("rs485_adapter", "Controller", "essential", "low", "USB to RS485 adapter",
              "Industrial type with galvanic isolation and ESD protection preferred", 1, "one RS485 bus",
              alternatives=["Hat/serial RS485 board (check Pi 5 compatibility)"],
              compat="Appears as /dev/ttyUSB0. Termination/bias options vary by adapter.",
              search="USB RS485 adapter isolated"))
    add(_line("ups", "Controller", "recommended", "recommended", "DC UPS / supervised shutdown module for the controller",
              "Keeps the Pi powered long enough to shut down cleanly", 1, "one controller", search="DC UPS 5V Raspberry Pi"))
    add(_line("switch", "Controller", "recommended", "recommended", "Ethernet switch (DIN-rail or small unmanaged)",
              "Wired link to the Pi; Wi-Fi is not recommended for the controller", 1, "one site",
              search="DIN rail ethernet switch"))
    add(_line("esp32", "Controller", "optional", "recommended", "ESP32 development board for remote node",
              "Wi-Fi/MQTT remote I/O node", o.esp32_nodes, f"{o.esp32_nodes} remote node(s) (your option)",
              compat="ESP32 nodes are not supported by this application yet.", search="ESP32 DevKit"))

    # ---- Climate sensing
    add(_line("sht35", "Climate sensing", "essential", "low", "Sensirion SHT35 temperature/humidity sensor (probe or board)",
              "I2C; repeatable, replaceable, supported by the sht3x driver", st,
              f"{st} climate stations (≥1 per {o.climate_station_area_m2:g} m², min {o.min_climate_stations})",
              manufacturer="Sensirion", model="SHT35",
              alternatives=["SHT31", "RS485 temperature/humidity transmitter (industrial, longer cable)"],
              compat="I2C cable length is limited: keep it short or use an RS485 transmitter / ESP32 node.",
              search="SHT35 sensor"))
    add(_line("rad_shield", "Climate sensing", "essential", "low", "Radiation shield / aspirated housing for climate sensors",
              "Stops sun and condensation falsifying readings", st, "one per climate station", search="radiation shield sensor"))
    add(_line("out_th", "Climate sensing", "recommended", "recommended", "Outdoor temperature/humidity sensor with weather shield",
              "Reference for ventilation/heating decisions", 1, "one site", search="outdoor temperature humidity sensor RS485"))
    add(_line("co2", "Climate sensing", "recommended", "recommended", "Sensirion SCD41 CO2 sensor (or industrial NDIR transmitter)",
              "True CO2 (photoacoustic) with T/RH", 1, "one per 200 m² (minimum)", manufacturer="Sensirion", model="SCD41",
              compat="No dedicated driver yet. Industrial NDIR RS485 transmitters use the generic Modbus driver.",
              search="SCD41"))
    add(_line("par", "Climate sensing", "recommended", "recommended", "PAR / quantum sensor (PPFD), preferably RS485/Modbus",
              "Measures photosynthetic photon flux density; lux sensors are NOT a substitute", 1, "one above canopy",
              search="quantum PAR sensor modbus"))
    add(_line("leaf_wet", "Climate sensing", "optional", "professional", "Leaf wetness sensor",
              "Disease-risk monitoring", 1, "one", search="leaf wetness sensor"))
    add(_line("pressure", "Climate sensing", "optional", "professional", "Atmospheric pressure sensor",
              "Optional context data", 1, "one", search="BME280 sensor"))

    # ---- Soil & hydroponic sensing
    if soil:
        add(_line("soil_probe", "Soil & hydroponic sensing", "essential", "low", "RS485/Modbus soil probe (moisture + temperature, EC if available)",
                  "Industrial probe preferred; cheap capacitive probes are indicators, not instruments", soil_probes,
                  f"{soil_zones} soil zone(s) × {o.soil_probes_per_zone} probes", search="soil moisture temperature EC sensor RS485",
                  compat="Register map comes from the probe datasheet (generic Modbus driver)."))
    if hydro:
        add(_line("ds18b20", "Soil & hydroponic sensing", "essential", "low", "DS18B20 waterproof temperature probe",
                  "1-Wire, nutrient solution temperature", tanks, f"{tanks} tank(s)", manufacturer="Analog Devices / Maxim",
                  model="DS18B20", search="DS18B20 waterproof probe"))
        add(_line("ph_probe", "Soil & hydroponic sensing", "essential", "low", "pH probe + transmitter (RS485 or isolated analogue)",
                  "Needs regular calibration and replacement", tanks, f"{tanks} tank(s)", search="pH probe transmitter RS485"))
        add(_line("ec_probe", "Soil & hydroponic sensing", "essential", "low", "EC probe + transmitter (RS485 or isolated analogue)",
                  "Needs regular calibration", tanks, f"{tanks} tank(s)", search="EC probe transmitter RS485"))
        add(_line("tank_level", "Soil & hydroponic sensing", "recommended", "recommended", "Continuous tank level sensor",
                  "Ultrasonic or pressure type", tanks, f"{tanks} tank(s)", search="water level sensor ultrasonic RS485"))
        add(_line("float_sw", "Soil & hydroponic sensing", "essential", "low", "Float switch for low-water cut-out (hard-wired to the pump circuit)",
                  "Independent hardware protection against dry running; not software-dependent", tanks + 1,
                  "1 per nutrient tank + 1 supply reservoir", search="float switch"))
    add(_line("flow_meter", "Soil & hydroponic sensing", "recommended", "recommended", "Flow meter (pulse or Modbus)",
              "Verifies irrigation and detects leaks/blockage", max(1, pump_count), "one per pumped circuit",
              search="water flow meter pulse"))
    add(_line("pressure_sensor", "Soil & hydroponic sensing", "recommended", "professional", "Pressure sensor (4-20 mA or RS485)",
              "Pump/filter monitoring", max(1, pump_count), "one per pumped circuit", search="pressure transmitter 4-20mA"))

    # ---- Irrigation
    miss_pump = [] if o.pump_flow_l_min else ["pump_flow_l_min"]
    add(_line("reservoir", "Irrigation", "essential", "low", "Water reservoir / tank",
              (f"≥ {irr['reservoir_min_l']:.0f} L for {o.autonomy_days:g} day(s) autonomy" if "reservoir_min_l" in irr else "Capacity needs your water demand"),
              1 if "reservoir_min_l" in irr else None, "one", qty_missing=[] if "reservoir_min_l" in irr else ["water_l_per_m2_day"],
              search="rezervor apa IBC"))
    if pump_count:
        add(_line("pump", "Irrigation", "essential", "low", "Irrigation pump",
                  "Flow/pressure from the zone calculation and your pump curve", pump_count, "one per soil circuit + one per hydroponic circuit",
                  qty_missing=miss_pump, search="pompa irigatii"))
        add(_line("pump_backup", "Irrigation", "optional", "professional", "Backup pump", "Same as main pump", pump_count,
                  "one spare per circuit", search="pompa irigatii"))
        add(_line("check_valve", "Irrigation", "essential", "low", "Check valve", "Matches pipe diameter", pump_count, "one per pump",
                  search="clapet antiretur"))
        add(_line("filter", "Irrigation", "essential", "low", "Irrigation filter (disc/screen)",
                  "Mesh must suit the dripper manufacturer's requirement", pump_count, "one per circuit", search="filtru irigatii disc"))
        add(_line("regulator", "Irrigation", "recommended", "recommended", "Pressure regulator", "Matches dripper operating pressure",
                  max(1, soil_zones), "one per soil zone group", search="regulator presiune irigatii"))
    add(_line("valves", "Irrigation", "essential", "low", "24 V DC solenoid valve (normally closed)",
              "Rated for line pressure and 24 V DC coil; consider latching types for low power", zones,
              f"{soil_zones} soil + {hydro_zones} hydroponic zone(s)", search="electrovalva 24V DC irigatii",
              compat="Switched by a DC MOSFET driver or relay with a flyback diode; 24 V supply sized in Electrical."))
    add(_line("manifold", "Irrigation", "essential", "low", "Irrigation manifold(s)", "Outlets for each zone", max(1, math.ceil(zones / 4)),
              "assumed 4 outlets per manifold (assumption)", search="distribuitor irigatii"))
    add(_line("drip_tube", "Irrigation", "essential", "low", "Drip tubing / drip line (m)",
              "Per the drip line total you entered", math.ceil(o.drip_line_total_m) if o.drip_line_total_m else None, "metres",
              qty_missing=[] if o.drip_line_total_m else ["drip_line_total_m"], search="tub picurare"))
    add(_line("drippers", "Irrigation", "essential", "low", "Drippers (if not integrated in the tubing)",
              "Flow rate from datasheet", irr.get("drippers"), "line length ÷ spacing",
              qty_missing=[] if "drippers" in irr else irr["missing"], search="picurator"))
    if hydro:
        add(_line("dosing", "Irrigation", "recommended", "recommended", "Dosing pumps (peristaltic) for fertigation",
                  "Nutrient A, B, pH down, pH up", 4, "4 channels (assumption)", search="peristaltic dosing pump 24V"))
    add(_line("drain", "Irrigation", "optional", "recommended", "Drainage pipe / sump pump", "Site-specific", None, "needs site design",
              qty_missing=["site drainage design"], search="drenaj"))

    # ---- Ventilation & climate
    add(_line("exhaust_fan", "Ventilation & climate", "essential", "low", "Exhaust fan",
              "Sized from air volume × target ACH ÷ (rated flow × derating)", vent["fans"], "airflow calculation",
              qty_missing=vent["missing"], search="ventilator axial 230V industrial"))
    add(_line("circ_fan", "Ventilation & climate", "recommended", "recommended", "Circulation (HAF) fan", "Per layout",
              o.circulation_fans, "your input", qty_missing=[] if o.circulation_fans is not None else ["circulation_fans"],
              search="ventilator circulare sera"))
    add(_line("vent_act", "Ventilation & climate", "essential", "low", "Linear actuator / rack-and-pinion motor for vent windows",
              "With limit switches; 24 V DC preferred", o.vent_actuators, "your input",
              qty_missing=[] if o.vent_actuators is not None else ["vent_actuators"], search="actuator liniar 24V ferestre sera"))
    if cfg.heating_required is not False:
        add(_line("heater", "Ventilation & climate", "essential", "low", "Heating equipment",
                  "Heat load needs the covering, height, location and target temperature", None, "needs heating load calculation",
                  qty_missing=["heating_required" if cfg.heating_required is None else "heat load"],
                  compat="Needs independent over-temperature cut-out and qualified installation.", search="incalzire sera"))
    add(_line("shading", "Ventilation & climate", "optional", "professional", "Automatic shading system",
              "Motor + screen", None, "needs layout", qty_missing=["layout"], search="sistem umbrire sera"))
    add(_line("humidifier", "Ventilation & climate", "optional", "professional", "Humidification / dehumidification",
              "Only if climate requires it", None, "needs climate analysis", qty_missing=["climate analysis"], search="umidificator sera"))

    # ---- Lighting
    add(_line("led", "Lighting", "optional", "recommended", "LED grow light fixtures",
              "Count from supplemental PPFD, fixture PPF and utilisation factor", lit.get("fixtures"), "lighting calculation",
              qty_missing=lit["missing"], search="LED grow light horticultural"))
    add(_line("light_ctrl", "Lighting", "optional", "recommended", "Lighting contactor / dimming controller",
              "Switching device rated for the lighting load", 1, "one", search="contactor DIN"))
    add(_line("energy_meter", "Lighting", "recommended", "recommended", "Modbus energy meter (DIN-rail)",
              "Energy monitoring; installed by an electrician", 1, "one per measured feeder", search="energy meter modbus DIN"))

    # ---- Electrical & safety
    psu_w = ele.get("psu_24v_min_w")
    add(_line("psu24", "Electrical & safety", "essential", "low", "24 V DC DIN-rail power supply",
              (f"≥ {psu_w:.0f} W (loads + {o.psu_margin:.0%} headroom)" if psu_w else "Rating needs your load list"),
              1 if psu_w else None, "one (add redundancy module for professional)",
              qty_missing=[] if psu_w else ["loads"], search="sursa DIN 24V"))
    add(_line("psu_redundancy", "Electrical & safety", "optional", "professional", "Redundancy module + second 24 V supply",
              "Same rating as main supply", 1, "one set", search="redundancy module 24V"))
    add(_line("din", "Electrical & safety", "essential", "low", "DIN rail (m)", "35 mm", 2, "assumption: 2 m", search="sina DIN 35mm"))
    add(_line("mosfet", "Electrical & safety", "essential", "low", "DC-rated MOSFET driver / relay module for 24 V loads",
              "Isolated inputs; flyback protection for inductive loads", dc_outputs or None, "one per DC output",
              qty_missing=[] if dc_outputs else ["outputs"], compat="3.3 V logic drive from Pi/ESP32 via isolation.",
              search="MOSFET module 24V DC isolated"))
    add(_line("relay_ind", "Electrical & safety", "recommended", "recommended", "Industrial relay / contactor modules for AC loads",
              "Rated for the load; wired and installed by an electrician", None, "per mains load",
              qty_missing=["mains load list"], search="contactor DIN"))
    add(_line("fuses", "Electrical & safety", "essential", "low", "DC fuses / miniature breakers with holders",
              "Ratings per load (see electrical calculation)", max(1, len(o.loads)), "one per DC feeder", search="fuse holder DIN"))
    add(_line("mcb_rcd", "Electrical & safety", "essential", "low", "Mains MCB and RCD protection",
              "Selected and installed by a qualified electrician", None, "per electrician's design",
              qty_missing=["electrician design"], search="RCD DIN"))
    add(_line("spd", "Electrical & safety", "recommended", "recommended", "Surge protection device",
              "Per electrician's design", 1, "one", search="SPD DIN"))
    add(_line("estop", "Electrical & safety", "essential", "low", "Emergency stop pushbutton (hardware, cuts actuator power)",
              "Independent of software", 1, "one (more at each entrance)", search="emergency stop pushbutton"))
    add(_line("earthing", "Electrical & safety", "essential", "low", "Earthing and bonding materials",
              "Per electrician's design", None, "per electrician's design", qty_missing=["electrician design"], search="priza pamant"))
    add(_line("rs485_cable", "Electrical & safety", "essential", "low", "Shielded twisted-pair cable for RS485 (m)",
              "Pair for A/B, shield; extra conductor for reference where the devices require it",
              math.ceil(o.rs485_cable_m * 1.1) if o.rs485_cable_m else None, "route length + 10% (assumption)",
              qty_missing=[] if o.rs485_cable_m else ["rs485_cable_m"], search="cablu ecranat RS485"))
    add(_line("terminals", "Electrical & safety", "essential", "low", "Terminal blocks and ferrules", "Assorted", 1, "one set", search="clema DIN"))
    add(_line("glands", "Electrical & safety", "essential", "low", "Cable glands (IP68)", "Assorted sizes", 1, "one set", search="presetupa IP68"))
    add(_line("ducts", "Electrical & safety", "recommended", "recommended", "Cable ducts / conduit", "UV-resistant outdoors", 1, "one set", search="canal cablu"))
    add(_line("connectors", "Electrical & safety", "recommended", "recommended", "Waterproof connectors", "IP67 for field sensors", 1, "one set", search="conector IP67 M12"))
    add(_line("encl_ip65", "Electrical & safety", "essential", "low", "IP65/IP66 control cabinet", "Size from layout", 1, "one", search="dulap electric IP65"))

    # ---- Spares / consumables / tools / installation
    add(_line("spare_sht35", "Spares", "spare", "recommended", "Spare SHT35 sensor", "", 1, "one", manufacturer="Sensirion", model="SHT35", search="SHT35 sensor"))
    add(_line("spare_valve", "Spares", "spare", "recommended", "Spare solenoid valve", "", 1, "one", search="electrovalva 24V DC"))
    add(_line("spare_fuses", "Spares", "spare", "low", "Spare fuses", "Assorted ratings in use", 1, "one set", search="fuse assortment"))
    add(_line("spare_ph", "Spares", "spare", "professional", "Spare pH probe", "pH probes are a wear item", 1 if hydro else 0, "one", search="pH probe"))
    add(_line("buffers", "Consumables", "consumable", "low", "pH 4.01 / 7.00 buffer solutions and EC standard", "For calibration", 1 if hydro else 0, "one set",
              search="pH buffer solution EC standard"))
    add(_line("ties", "Consumables", "consumable", "low", "UV cable ties, tape, thread seal tape", "", 1, "one set", search="coliere cablu UV"))
    add(_line("tool_meter", "Tools", "tool", "low", "Multimeter (CAT III or better)", "", 1, "one", search="multimetru"))
    add(_line("tool_crimp", "Tools", "tool", "low", "Ferrule crimper, wire strippers, screwdriver set", "", 1, "one set", search="clesti sertizare"))
    add(_line("tool_usb", "Tools", "tool", "low", "Laptop/PC with SSH client and Ethernet cable", "Often already owned", 0, "assumed owned", search=""))
    add(_line("pipe", "Installation materials", "installation", "low", "PE pipe, fittings and clamps for water distribution",
              "From site design", None, "needs hydraulic layout", qty_missing=["hydraulic layout"], search="teava PE irigatii"))
    add(_line("mounts", "Installation materials", "installation", "low", "Mounting hardware (brackets, screws, anchors)", "", 1, "one set", search="suporti montaj"))
    return B


def filter_lines(lines: list[BomLine], tier: str, include_optional: bool = True) -> list[BomLine]:
    t = TIER_ORDER[tier]
    out = [ln for ln in lines if TIER_ORDER[ln.min_tier] <= t]
    if not include_optional:
        out = [ln for ln in out if ln.group != "optional"]
    return [ln for ln in out if ln.qty != 0]
