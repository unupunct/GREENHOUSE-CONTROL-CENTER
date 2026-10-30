# Hardware list (200 m² greenhouse, default assumptions)

*Generated 2026-10-30 by `scripts/make_hardware_list.py` from the planner of a running installation (10 m x 20 m = 200 m², soil and hydroponics). Regenerate it, or open the Shopping page, for YOUR greenhouse: quantities change with size, growing method and the inputs you give the planner.*

## How to read this list

- **Qty** is calculated from the planner. **?** means the quantity cannot be calculated until you supply the inputs named in the *Needs* column (for example fan airflow from the datasheet of the fan you choose). The application never guesses them.
- **From tier**: *all* = part of the low-cost configuration and above; *recommended +* = recommended and professional; *professional only*.
- Items are **generic requirements** ("24 V DIN-rail supply") unless a real product is named. No specification, price or link is invented: where a price is shown it was read from a supplier page on the date given; everything else is **no price recorded**, which means *not researched*, not *free*.
- Heuristic counts (climate stations per area, probes per zone, manifold outlets) are editable assumptions: see the Planner page.
- Mains-side items (breakers, RCD, contactors, earthing) are listed so you can brief an electrician; **they must be designed and installed by a qualified electrician.** Hardware protections (float switch in the pump circuit, hardware e-stop, heater over-temperature cut-out, window limit switches) are part of the list on purpose: the software is not allowed to be the only protection.

Supporting facts: the planner computes a soil area of 100 m² and hydroponic area of 100 m² (50/50 split assumption), 2 climate stations, 2 soil irrigation zone(s) of at most 50 m² and 1 hydroponic zone(s). The recommended controller is *Raspberry Pi 5 (4 GB) with active cooling and SSD or high-endurance storage*.

## Controller

| Item | Qty | From tier | Requirement / notes | Needs | Price |
|---|---|---|---|---|---|
| Raspberry Pi 5, 4 GB | 1 | all | Central controller running this application *Alternatives:* Raspberry Pi 4 Model B 4GB; Raspberry Pi 5 8GB. Raspberry Pi OS 64-bit. Needs its own supply, case/cooler and storage. | one controller | 639.00 RON (verified 2026-10-30) |
| Raspberry Pi USB-C power supply (official, for the chosen model) | 1 | all | 5 V USB-C; Pi 5: 5 V/5 A class | one controller | no price recorded |
| Active cooler for Raspberry Pi 5 | 1 | recommended + | Fan + heatsink | one controller | no price recorded |
| High-endurance microSD card, 32-64 GB | 2 | all | Rated for continuous recording (dashcam/surveillance class) | 1 in use + 1 prepared spare | no price recorded |
| M.2 HAT + NVMe SSD (or USB SSD) | 1 | recommended + | Better write endurance than microSD Pi 5 only (PCIe). On Pi 4 use a USB-attached SSD. | one controller | no price recorded |
| Enclosure for the Raspberry Pi (IP65 if in the greenhouse) | 1 | all | Ventilated or fanless depending on location | one controller | no price recorded |
| USB to RS485 adapter | 1 | all | Industrial type with galvanic isolation and ESD protection preferred *Alternatives:* Hat/serial RS485 board (check Pi 5 compatibility). Appears as /dev/ttyUSB0. Termination/bias options vary by adapter. | one RS485 bus | no price recorded |
| DC UPS / supervised shutdown module for the controller | 1 | recommended + | Keeps the Pi powered long enough to shut down cleanly | one controller | no price recorded |
| Ethernet switch (DIN-rail or small unmanaged) | 1 | recommended + | Wired link to the Pi; Wi-Fi is not recommended for the controller | one site | no price recorded |

## Climate sensing

| Item | Qty | From tier | Requirement / notes | Needs | Price |
|---|---|---|---|---|---|
| Sensirion SHT35 temperature/humidity sensor (probe or board) | 2 | all | I2C; repeatable, replaceable, supported by the sht3x driver *Alternatives:* SHT31; RS485 temperature/humidity transmitter (industrial, longer cable). I2C cable length is limited: keep it short or use an RS485 transmitter / ESP32 node. | 2 climate stations (≥1 per 100 m², min 2) | no price recorded |
| Radiation shield / aspirated housing for climate sensors | 2 | all | Stops sun and condensation falsifying readings | one per climate station | no price recorded |
| Outdoor temperature/humidity sensor with weather shield | 1 | recommended + | Reference for ventilation/heating decisions | one site | no price recorded |
| Sensirion SCD41 CO2 sensor (or industrial NDIR transmitter) | 1 | recommended + | True CO2 (photoacoustic) with T/RH No driver yet (Phase 2 list). Industrial NDIR RS485 transmitters use the generic Modbus driver. | one per 200 m² (minimum) | no price recorded |
| PAR / quantum sensor (PPFD), preferably RS485/Modbus | 1 | recommended + | Measures photosynthetic photon flux density; lux sensors are NOT a substitute | one above canopy | no price recorded |
| Leaf wetness sensor | 1 | professional only | Disease-risk monitoring | one | no price recorded |
| Atmospheric pressure sensor | 1 | professional only | Optional context data | one | no price recorded |

## Soil & hydroponic sensing

| Item | Qty | From tier | Requirement / notes | Needs | Price |
|---|---|---|---|---|---|
| RS485/Modbus soil probe (moisture + temperature, EC if available) | 4 | all | Industrial probe preferred; cheap capacitive probes are indicators, not instruments Register map comes from the probe datasheet (generic Modbus driver). | 2 soil zone(s) × 2 probes | no price recorded |
| DS18B20 waterproof temperature probe | 1 | all | 1-Wire, nutrient solution temperature | 1 tank(s) | no price recorded |
| pH probe + transmitter (RS485 or isolated analogue) | 1 | all | Needs regular calibration and replacement | 1 tank(s) | no price recorded |
| EC probe + transmitter (RS485 or isolated analogue) | 1 | all | Needs regular calibration | 1 tank(s) | no price recorded |
| Continuous tank level sensor | 1 | recommended + | Ultrasonic or pressure type | 1 tank(s) | no price recorded |
| Float switch for low-water cut-out (hard-wired to the pump circuit) | 2 | all | Independent hardware protection against dry running; not software-dependent | 1 per nutrient tank + 1 supply reservoir | no price recorded |
| Flow meter (pulse or Modbus) | 2 | recommended + | Verifies irrigation and detects leaks/blockage | one per pumped circuit | no price recorded |
| Pressure sensor (4-20 mA or RS485) | 2 | professional only | Pump/filter monitoring | one per pumped circuit | no price recorded |

## Irrigation

| Item | Qty | From tier | Requirement / notes | Needs | Price |
|---|---|---|---|---|---|
| Water reservoir / tank | ? | all | Capacity needs your water demand | water_l_per_m2_day | no price recorded |
| Irrigation pump | 2 | all | Flow/pressure from the zone calculation and your pump curve | pump_flow_l_min | no price recorded |
| Backup pump | 2 | professional only | Same as main pump | one spare per circuit | no price recorded |
| Check valve | 2 | all | Matches pipe diameter | one per pump | no price recorded |
| Irrigation filter (disc/screen) | 2 | all | Mesh must suit the dripper manufacturer's requirement | one per circuit | no price recorded |
| Pressure regulator | 2 | recommended + | Matches dripper operating pressure | one per soil zone group | no price recorded |
| 24 V DC solenoid valve (normally closed) | 3 | all | Rated for line pressure and 24 V DC coil; consider latching types for low power Switched by a DC MOSFET driver or relay with a flyback diode; 24 V supply sized in Electrical. | 2 soil + 1 hydroponic zone(s) | no price recorded |
| Irrigation manifold(s) | 1 | all | Outlets for each zone | assumed 4 outlets per manifold (assumption) | no price recorded |
| Drip tubing / drip line (m) | ? | all | Per the drip line total you entered | drip_line_total_m | no price recorded |
| Drippers (if not integrated in the tubing) | ? | all | Flow rate from datasheet | drip_line_total_m, dripper_flow_l_h, dripper_spacing_m, water_l_per_m2_day | no price recorded |
| Dosing pumps (peristaltic) for fertigation | 4 | recommended + | Nutrient A, B, pH down, pH up | 4 channels (assumption) | no price recorded |
| Drainage pipe / sump pump | ? | recommended + | Site-specific | site drainage design | no price recorded |

## Ventilation & climate

| Item | Qty | From tier | Requirement / notes | Needs | Price |
|---|---|---|---|---|---|
| Exhaust fan | ? | all | Sized from air volume × target ACH ÷ (rated flow × derating) | ach_target | no price recorded |
| Circulation (HAF) fan | ? | recommended + | Per layout | circulation_fans | no price recorded |
| Linear actuator / rack-and-pinion motor for vent windows | ? | all | With limit switches; 24 V DC preferred | vent_actuators | no price recorded |
| Heating equipment | ? | all | Heat load needs the covering, height, location and target temperature Needs independent over-temperature cut-out and qualified installation. | heat load | no price recorded |
| Automatic shading system | ? | professional only | Motor + screen | layout | no price recorded |
| Humidification / dehumidification | ? | professional only | Only if climate requires it | climate analysis | no price recorded |

## Lighting

| Item | Qty | From tier | Requirement / notes | Needs | Price |
|---|---|---|---|---|---|
| LED grow light fixtures | ? | recommended + | Count from supplemental PPFD, fixture PPF and utilisation factor | dli_target, natural_dli, photoperiod_h | no price recorded |
| Lighting contactor / dimming controller | 1 | recommended + | Switching device rated for the lighting load | one | no price recorded |
| Modbus energy meter (DIN-rail) | 1 | recommended + | Energy monitoring; installed by an electrician | one per measured feeder | no price recorded |

## Electrical & safety

| Item | Qty | From tier | Requirement / notes | Needs | Price |
|---|---|---|---|---|---|
| 24 V DC DIN-rail power supply | ? | all | Rating needs your load list | loads | no price recorded |
| Redundancy module + second 24 V supply | 1 | professional only | Same rating as main supply | one set | no price recorded |
| DIN rail (m) | 2 | all | 35 mm | assumption: 2 m | no price recorded |
| DC-rated MOSFET driver / relay module for 24 V loads | 3 | all | Isolated inputs; flyback protection for inductive loads 3.3 V logic drive from Pi/ESP32 via isolation. | one per DC output | no price recorded |
| Industrial relay / contactor modules for AC loads | ? | recommended + | Rated for the load; wired and installed by an electrician | mains load list | no price recorded |
| DC fuses / miniature breakers with holders | 1 | all | Ratings per load (see electrical calculation) | one per DC feeder | no price recorded |
| Mains MCB and RCD protection | ? | all | Selected and installed by a qualified electrician | electrician design | no price recorded |
| Surge protection device | 1 | recommended + | Per electrician's design | one | no price recorded |
| Emergency stop pushbutton (hardware, cuts actuator power) | 1 | all | Independent of software | one (more at each entrance) | no price recorded |
| Earthing and bonding materials | ? | all | Per electrician's design | electrician design | no price recorded |
| Shielded twisted-pair cable for RS485 (m) | ? | all | Pair for A/B, shield; extra conductor for reference where the devices require it | rs485_cable_m | no price recorded |
| Terminal blocks and ferrules | 1 | all | Assorted | one set | no price recorded |
| Cable glands (IP68) | 1 | all | Assorted sizes | one set | no price recorded |
| Cable ducts / conduit | 1 | recommended + | UV-resistant outdoors | one set | no price recorded |
| Waterproof connectors | 1 | recommended + | IP67 for field sensors | one set | no price recorded |
| IP65/IP66 control cabinet | 1 | all | Size from layout | one | no price recorded |

## Spares

| Item | Qty | From tier | Requirement / notes | Needs | Price |
|---|---|---|---|---|---|
| Spare SHT35 sensor | 1 | recommended + |  | one | no price recorded |
| Spare solenoid valve | 1 | recommended + |  | one | no price recorded |
| Spare fuses | 1 | all | Assorted ratings in use | one set | no price recorded |
| Spare pH probe | 1 | professional only | pH probes are a wear item | one | no price recorded |

## Consumables

| Item | Qty | From tier | Requirement / notes | Needs | Price |
|---|---|---|---|---|---|
| pH 4.01 / 7.00 buffer solutions and EC standard | 1 | all | For calibration | one set | no price recorded |
| UV cable ties, tape, thread seal tape | 1 | all |  | one set | no price recorded |

## Tools

| Item | Qty | From tier | Requirement / notes | Needs | Price |
|---|---|---|---|---|---|
| Multimeter (CAT III or better) | 1 | all |  | one | no price recorded |
| Ferrule crimper, wire strippers, screwdriver set | 1 | all |  | one set | no price recorded |

## Installation materials

| Item | Qty | From tier | Requirement / notes | Needs | Price |
|---|---|---|---|---|---|
| PE pipe, fittings and clamps for water distribution | ? | all | From site design | hydraulic layout | no price recorded |
| Mounting hardware (brackets, screws, anchors) | 1 | all |  | one set | no price recorded |

## Totals

71 lines (professional view incl. optional). Priced lines total 639.00 RON; **70 lines have no recorded price**, 17 quantities still need inputs. A complete budget cannot be stated until you research prices: see BUDGET.md.

## What this list does not include

Mains installation design and labour, greenhouse structure and covering, groundwater/water supply connection, heating equipment sizing (the application does not calculate a heat load), crop inputs, nutrients, running costs, shipping and duties.
