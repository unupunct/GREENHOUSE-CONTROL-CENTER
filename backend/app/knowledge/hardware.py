"""Hardware encyclopedia content.

Pages are generated from CATEGORY text (what/how/why/wiring/installation/
configuration/calibration/troubleshooting/maintenance) merged with ITEM facts.
Rules of this file:
  * no prices, no URLs, no stock: those come only from recorded offers (see api/encyclopedia.py)
  * specification numbers appear only for parts whose datasheet values are well established,
    and are labelled "manufacturer datasheet: verify before relying on it"
  * "replacement interval" is a rule of thumb unless stated otherwise, and says so
"""

from __future__ import annotations

SPEC_NOTE = "Manufacturer datasheet values as generally published: verify against the datasheet of the exact part you buy."


def C(id_, title, what, how, why, wiring, installation, configuration, calibration, troubleshooting, maintenance,
      interval, basis="rule of thumb"):
    return dict(id=id_, title=title, what=what, how=how, why=why, wiring=wiring, installation=installation,
                configuration=configuration, calibration=calibration, troubleshooting=troubleshooting,
                maintenance=maintenance, replacement={"interval": interval, "basis": basis})


CATEGORIES: list[dict] = [
    C("raspberry_pi", "Raspberry Pi models",
      "A single-board computer that runs the Greenhouse Control Center: web interface, database, automation, drivers.",
      "A multi-core Arm CPU running Linux (Raspberry Pi OS) with a 40-pin GPIO header, USB, Ethernet and Wi-Fi. It has no analogue inputs.",
      "It is the central controller: everything else (sensors, outputs, ESP32 nodes) talks to it.",
      "Power through USB-C with a supply rated for the model. GPIO pins are 3.3 V logic and are not protected for mains, 5 V or inductive loads: drive isolated modules only. I2C is on GPIO2/3, 1-Wire defaults to GPIO4.",
      "Mount in a ventilated or fan-cooled enclosure away from condensation. Use a stable supply, a high-endurance card or SSD, and cabling that cannot be pulled out accidentally.",
      "Flash Raspberry Pi OS 64-bit, enable SSH, give it a fixed address, enable I2C/1-Wire as needed (RASPBERRY_PI_SETUP.md).",
      "Not applicable (the board has no sensor). Keep the clock correct; reports depend on it.",
      ["Random reboots or freezes: under-voltage (weak supply/cable), failing storage, overheating.", "Corrupted data after power loss: no UPS/clean shutdown, microSD wear.",
       "Not reachable on the network: IP changed (use a DHCP reservation), Wi-Fi dropped (prefer Ethernet)."],
      "Keep the OS updated, check storage health and free space, check cooling and dust, test backups.",
      "Boards run for years; microSD cards are the usual wear item: replace on errors or after roughly 2-3 years of continuous use."),
    C("esp32", "ESP32 models",
      "A low-cost Wi-Fi/Bluetooth microcontroller board used as a remote I/O node that reports to the controller over MQTT.",
      "A dual-core 3.3 V microcontroller with I2C, SPI, UART, GPIO, PWM and an on-chip ADC, running firmware you flash.",
      "It lets sensors and outputs sit far from the Raspberry Pi without long I2C cables.",
      "3.3 V logic only. Power through USB or a regulated 5 V supply. Sensors on I2C/1-Wire/RS485 transceivers connect as on the Pi.",
      "Mount in a small IP-rated box, strain-relieve cables, supply it from the cabinet's 5 V rail, and keep Wi-Fi coverage good.",
      "ESP32 firmware and MQTT node support are NOT implemented in this application yet (see STATUS.md).",
      "The on-chip ADC is non-linear and noisy: use an external ADC for measurements.",
      ["Node drops off: Wi-Fi signal or power brown-out.", "Wrong readings on analogue pins: use an external ADC.", "Boot loops: unstable 5 V supply or a pin held in a boot-strapping state."],
      "Check power and Wi-Fi signal; update firmware deliberately.", "Typically years; replace on instability or water damage."),
    C("temperature", "Temperature sensors",
      "Measure air, soil, water or nutrient-solution temperature.",
      "Digital sensors (1-Wire, I2C, RS485) deliver a calibrated value over a bus; analogue thermistors/RTDs need a conditioning circuit and ADC.",
      "Temperature drives ventilation, heating, cooling, VPD and plant health.",
      "Digital 1-Wire probes use three wires (supply, ground, data with a pull-up resistor). Keep bus lengths and branches short; use shielded cable for long runs.",
      "Air sensors: in a radiation shield, at crop height, away from heaters, fans and direct sun. Water probes: submerged and secured.",
      "Register in Advanced → Hardware with the matching driver and zone. Set valid min/max to catch faults.",
      "Compare with a trusted reference in a stable bath or room; apply a one-point offset (CALIBRATION_GUIDE.md).",
      ["No reading: wiring, supply, pull-up, wrong ID.", "Reads constantly high: sun on the sensor, heat from electronics.", "Spikes or CRC errors: cable too long, loose connector, electrical noise."],
      "Clean shields; check connectors for corrosion; compare against a reference occasionally.", "Often many years; replace if readings drift or the cable is damaged."),
    C("humidity", "Humidity sensors",
      "Measure relative humidity (and usually temperature) of the air.",
      "A capacitive polymer element changes capacitance with moisture; the chip converts it to a digital value.",
      "Humidity with temperature gives VPD and condensation risk, which drive ventilation and disease control.",
      "I2C parts: supply, ground, SDA, SCL (Pi: GPIO2/GPIO3). Keep I2C cables short, or use an RS485 transmitter / ESP32 node for distant spots.",
      "In a ventilated radiation shield, at canopy height, protected from direct water spray and condensation.",
      "Register one row per quantity (temperature and humidity) with the same address.",
      "Compare with a reference hygrometer or salt-solution test; humidity elements drift and recover slowly after wetting.",
      ["Stuck near 100 %: condensation on the element, damaged sensor.", "Slow response: dust or filter cap clogged.", "CRC errors: bus noise or cable too long."],
      "Keep the sensor clean and dry; replace if it drifts or has been condensed on repeatedly.", "Humidity elements age in greenhouses: plan to check yearly and replace when drift cannot be corrected."),
    C("soil_moisture", "Soil moisture sensors",
      "Estimate how wet the soil or substrate is.",
      "Capacitive or dielectric probes measure how the medium changes the electrical field; the reading depends on soil type, density and salinity.",
      "Moisture triggers irrigation and avoids over- and under-watering.",
      "Industrial probes use RS485/Modbus (A/B pair plus supply); cheap probes give an analogue voltage that needs an ADC. Treat cheap capacitive probes as indicators, not instruments.",
      "Insert fully into the root zone with good soil contact, away from drippers' direct stream; use at least two per irrigation zone.",
      "Use the generic Modbus driver with the register map from the probe's datasheet; calibrate for YOUR soil.",
      "Measure wet and dry samples of your medium and apply a two-point calibration.",
      ["Reads the same wet or dry: no soil contact, wrong register, wrong scale.", "Drifts over weeks: salt build-up, corrosion at the electrodes.", "No Modbus reply: address, baud, A/B swapped (MODBUS_SETUP.md)."],
      "Re-check contact and calibration each season; clean the probe.", "Industrial probes last years; cheap capacitive probes may corrode within months."),
    C("co2", "CO2 sensors",
      "Measure carbon dioxide concentration in ppm.",
      "NDIR sensors measure infrared absorption by CO2; photoacoustic sensors detect sound from absorbed pulses. Many include temperature and humidity.",
      "CO2 informs ventilation decisions, optional enrichment and, for people, safety.",
      "I2C or RS485 depending on the model; allow warm-up time and keep away from your breath and the exhaust of heaters.",
      "At canopy height in a representative place, not in dead air nor in the direct stream of a fan or enrichment outlet.",
      "Register with the matching driver; this application has no CO2 driver yet beyond the generic Modbus driver.",
      "Sensors self-calibrate to varying degrees; compare with outdoor air (about the ambient outdoor level) when possible.",
      ["Constant 400-ish ppm: sensor in outdoor air only or stuck.", "Jumps: dust, condensation, unstable supply.", "Reads high near people or heaters: local sources."],
      "Keep clean and dry; verify against fresh outdoor air twice a year.", "Several years; replace when it cannot hold calibration."),
    C("light", "Light sensors (illuminance)",
      "Measure light as perceived by the human eye (lux).",
      "A photodiode with a human-eye response filter converts light to a digital or analogue value.",
      "Useful for day/night logic, but NOT for plant light: plants respond to photons (PPFD), not lux, and the two are not interchangeable.",
      "I2C or analogue depending on the part.", "Horizontal, unshaded, under the covering at canopy height.",
      "Register with the matching driver or generic Modbus driver.", "Compare with a reference lux meter.",
      ["Reads zero by day: blocked or wrong address.", "Saturates: sensor range too small for full sun."], "Keep the window clean.", "Years; replace on drift or damage."),
    C("par", "PAR (quantum) sensors",
      "Measure photosynthetically active radiation as photon flux density (PPFD, µmol m⁻² s⁻¹).",
      "A calibrated silicon sensor with a filter approximates the 400-700 nm quantum response; output is analogue or digital (RS485).",
      "PPFD feeds DLI monitoring and lighting control: it is the correct measure of light for plants.",
      "RS485/Modbus models need supply and A/B; analogue models need an ADC and a stable reference.",
      "Level, above the canopy, unshaded, with a clean diffuser; one per lighting zone if conditions differ.",
      "Add as a PAR sensor in the greenhouse zone; DLI calculations use it automatically.",
      "Factory calibration is usually good for a year or two; compare against a reference quantum sensor.",
      ["Zero at noon: blocked or wrong register.", "Low readings: dirty diffuser.", "Different from a reference: spectrum mismatch under LEDs; check the sensor's stated spectral error."],
      "Clean the diffuser; recalibrate periodically.", "Often recalibrated every 1-2 years (rule of thumb); replace if damaged."),
    C("ph", "pH probes",
      "Measure acidity of nutrient solution or substrate leachate.",
      "A glass electrode develops a voltage that depends on pH; a transmitter converts it to RS485 or an isolated analogue signal.",
      "pH controls nutrient availability in hydroponics.",
      "Use a transmitter (preferably isolated). Keep the probe cable short and shielded; never let two probes share a poorly isolated supply in the same solution.",
      "Fully submerged in a well-mixed spot, away from dosing inlets, never allowed to dry out.",
      "Register with the Modbus driver using the transmitter's register map, or an isolated analogue input via an ADC.",
      "Two-point calibration with fresh pH 7.00 and 4.01 buffers; check slope. Calibrate regularly.",
      ["Slow or drifting: aged electrode, dirty glass.", "Noisy: ground loops, unshielded cable.", "Reads 7 always: disconnected probe or dried electrode."],
      "Calibrate often, clean, store wet in storage solution; compare with a hand meter.", "pH electrodes are consumables: commonly about 1-2 years, shorter in nutrient solution (rule of thumb)."),
    C("ec", "EC probes",
      "Measure electrical conductivity, a proxy for total dissolved nutrients.",
      "Electrodes measure conductance of the solution; a transmitter applies temperature compensation and reports mS/cm.",
      "EC tells you how strong the nutrient solution is.",
      "RS485 or isolated analogue transmitter with shielded cable.", "Submerged where solution is well mixed, away from inlets, with temperature compensation.",
      "Register with the Modbus driver using the transmitter's register map.", "One- or two-point calibration with EC standard solutions.",
      ["Reads low: fouled electrodes or air bubbles.", "Jumpy: bubbles, noise, poor cable.", "Offset after cleaning: re-calibrate."],
      "Clean electrodes, check cell constant, calibrate.", "Longer-lived than pH probes; replace when it can no longer be calibrated."),
    C("water_level", "Water-level sensors",
      "Detect or measure the level of water in a tank.",
      "Float switches open/close with the level; continuous sensors use ultrasonic echo, hydrostatic pressure or capacitance.",
      "A level interlock protects pumps from running dry. A float switch wired into the pump circuit is an independent hardware protection.",
      "Float switch: two wires (dry contact) to a digital input and, for protection, in series with the pump control circuit. Continuous sensors: RS485 or 4-20 mA.",
      "Mount so the float moves freely, away from inlet turbulence; ultrasonic sensors need a clear cone and a flat surface.",
      "Create a tank and assign the level sensor and/or float switch sensor; set the minimum level.",
      "Continuous sensors: record empty and full readings. Float switches: test by lifting.",
      ["Level stuck: float jammed by debris.", "Ultrasonic noise: foam, condensation, obstructions.", "Pump refuses to start: interlock says level low or no fresh reading."],
      "Inspect floats and clean tanks; test the low-level cut-out regularly.", "Float switches commonly last years; replace if sticky (rule of thumb)."),
    C("flow", "Flow meters",
      "Measure water flow in a pipe.",
      "Turbine/paddle meters emit pulses proportional to volume; electromagnetic and ultrasonic meters give a signal or Modbus value.",
      "Confirms irrigation is flowing, measures water use and detects dry running, blockage and leaks.",
      "Pulse meters: supply, ground, pulse output (watch voltage levels: 5 V pulses need a level shifter or open-collector with pull-up to 3.3 V). Modbus meters: A/B pair.",
      "In a straight pipe run per the manufacturer, downstream of the filter, orientation as specified.",
      "Zone flow limits are YOUR values. Pulse-counting inputs are not implemented yet: use a Modbus meter or a pulse-to-Modbus converter.",
      "Compare with a measured volume (bucket and timer) and adjust scaling.",
      ["Zero flow with pump running: air lock, blocked filter, wrong orientation.", "Erratic: air bubbles, debris on the turbine.", "Reads flow when off: leak or noise."],
      "Clean strainers and the meter, check for debris and leaks.", "Moving-part meters wear and clog; replace when readings cannot be trusted."),
    C("pumps", "Pumps",
      "Move irrigation water or nutrient solution (and dose concentrates).",
      "Centrifugal pumps spin an impeller; diaphragm and peristaltic pumps move fixed volumes per stroke or rotation.",
      "Pressure and flow for irrigation and fertigation.",
      "Mains pumps are switched by a contactor or relay installed by an electrician; small DC pumps by a MOSFET driver. Add dry-run protection independent of software.",
      "Below tank level where possible (flooded suction), with a check valve, filter and pressure relief as designed; provide drainage and keep electrics dry.",
      "Register as an output of kind 'pump' with a maximum runtime; assign it to zones with a tank.",
      "Not applicable; verify flow and pressure against the pump curve.",
      ["Runs but no flow: air in pump, blocked suction, dry tank.", "Trips breaker: seized impeller, wiring fault.", "Overheats: running dead-headed or dry (the software forbids both; hardware protection must too)."],
      "Inspect seals, listen for noise, clean the suction filter, check mounting and electrical safety.", "Depends heavily on duty and water quality: inspect regularly, replace seals/impellers when worn (rule of thumb)."),
    C("valves", "Solenoid valves",
      "Open or close water flow electrically.",
      "A coil lifts or releases a plunger or diaphragm. Normally-closed valves close when power is removed (fail-safe).",
      "Select which irrigation zone receives water.",
      "Coil voltage must match the supply (24 V DC suits DIN-rail supplies). Switch through a MOSFET driver or relay with a flyback diode; fuse each feeder.",
      "Upstream filter, correct flow direction, minimum pressure as specified, accessible for maintenance.",
      "Register as an output of kind 'valve' with a maximum runtime, one per zone.",
      "Not applicable.",
      ["Valve will not open: low pressure, no coil voltage, burnt coil.", "Leaks when closed: debris on the seat.", "Buzzing or hot coil: wrong voltage type (AC vs DC) or continuous long energisation."],
      "Clean diaphragms and filters, check coils and wiring.", "Rule of thumb: inspect yearly, replace diaphragms or the valve when leaking."),
    C("fans", "Fans",
      "Move air: exhaust fans for ventilation, circulation fans inside the crop.",
      "Axial or centrifugal impellers driven by AC or DC motors; airflow falls as static pressure rises.",
      "Ventilation removes heat and humidity; circulation evens out climate and reduces disease.",
      "AC fans are switched by a contactor installed by an electrician; DC fans by drivers. Heaters should require a circulation fan (interlock).",
      "Exhaust opposite the intake openings, with louvres or shutters, guarded against contact; size from airflow requirements (VENTILATION_GUIDE.md).",
      "Register as outputs of kind 'fan'; use the Planner for count and the rule builder for control.",
      "Not applicable.",
      ["Low airflow: blocked screens, closed intake, wrong rotation.", "Noise or vibration: dirty or damaged blades.", "Trips: overload or failing motor."],
      "Clean blades and guards, check bearings and mounts, check louvres move freely.", "Bearings wear: inspect regularly and replace motors when noisy or hot (rule of thumb)."),
    C("actuators", "Linear actuators and window motors",
      "Open and close vent windows and screens.",
      "A DC motor with a gearbox or rack drives the window; limit switches stop it at the ends.",
      "Natural ventilation and shading.",
      "Two relays or a motor driver for open/close; they must never be energised together; limit switches in the motor circuit; 24 V DC is common.",
      "Mount rigidly in line with the load; fit end limit switches or use actuators with built-in limits; provide manual release if possible.",
      "Create two 'motor' outputs and a window with the full travel time; add rain and wind sensors for vents.",
      "Measure travel time end to end; the app estimates position from time and corrects at limit switches.",
      ["Stops short: limit switch or obstruction.", "Position drifts: dead reckoning error; fully close to re-home.", "Jams or overloads: binding hinges."],
      "Lubricate hinges, check mounts and limit switches, test rain/wind closing.", "Gearboxes and brushes wear: replace on slow travel or noise (rule of thumb)."),
    C("relays", "Relays and contactors",
      "Electrically operated switches that let a small control signal switch a larger load.",
      "A coil moves contacts (electromechanical) or a semiconductor switches the load (solid-state).",
      "Isolation between low-voltage control and loads.",
      "Never connect mains to Raspberry Pi GPIO or to hobby relay boards. Use DIN-rail contactors/industrial relays rated for the load, installed by an electrician; coils driven through an isolated driver.",
      "In the control cabinet on DIN rail, with correct ratings, fusing and terminal labelling.",
      "Modbus relay boards are driven with the 'modbus_coil' output driver.",
      "Not applicable.",
      ["Chattering: weak coil supply.", "Welded contacts: overload or no suppression: replace and fix the cause.", "Does not switch: no coil voltage, wrong coil type."],
      "Inspect for heating and discoloured terminals; tighten terminals.", "Contacts wear with switching cycles: replace per the manufacturer's rated life."),
    C("mosfet", "MOSFET drivers",
      "Switch DC loads (valves, small pumps, motors) from a logic signal.",
      "A power MOSFET with a gate driver and isolation switches the DC load; a flyback diode protects against inductive spikes.",
      "Efficient, silent switching of 24 V DC loads from 3.3 V signals.",
      "Opto-isolated inputs from GPIO; load power on separate terminals; fuse each channel; use DC-rated parts only (never for AC mains).",
      "In the cabinet, away from heat sources, with short, labelled wiring.",
      "Use with the GPIO output driver (BCM pin) and choose 'active_high' to match the module.",
      "Not applicable.",
      ["Output always on: shorted MOSFET or wrong polarity.", "Never switches: logic level, ground reference, supply missing.", "Gets hot: load too large or too frequent switching."],
      "Check terminals and heating.", "Long life when not overloaded; replace after any overload."),
    C("power_supplies", "Power supplies",
      "Convert mains to the DC voltages the system needs.",
      "Switch-mode supplies regulate output voltage with isolation from mains.",
      "Reliable 24 V for actuators and regulated 5 V for the Raspberry Pi.",
      "Mains side by an electrician with proper protection. Size the 24 V supply from the load list plus headroom (Planner). Keep Pi supply separate and clean.",
      "DIN-rail units in the cabinet with ventilation space; fuse every output feeder.",
      "Not applicable.", "Check the output voltage under load with a meter.",
      ["Voltage dips: overloaded or failing supply.", "Hum or heat: overload or poor ventilation.", "Pi under-voltage warnings: weak or long supply cable."],
      "Check temperature, dust and output voltage periodically.", "Electrolytic capacitors age: many supplies are rated for years at moderate temperature; plan to replace older units proactively."),
    C("ups", "UPS systems",
      "Keep the controller powered through short outages and allow a clean shutdown.",
      "A battery (lead-acid or lithium) with a charger and converter feeds the load when mains fails.",
      "Prevents storage corruption and keeps monitoring alive.",
      "Between the Pi power supply and the Pi; DC UPS modules suit small controllers. Battery must be sized for the shutdown time.",
      "Ventilated, away from heat and water, with fused battery connections.",
      "Shutdown signalling is not implemented in this application yet; monitor a battery voltage sensor if available.",
      "Check battery voltage against the manufacturer's curve.",
      ["Short runtime: aged battery.", "Pi reboots on mains loss: UPS too small or not connected correctly."],
      "Test by pulling mains periodically; check battery condition.", "Batteries wear: commonly a few years (rule of thumb)."),
    C("rs485_adapters", "RS485 adapters",
      "Connect the Raspberry Pi (USB) to an RS485 bus.",
      "A converter turns USB serial into the differential A/B signalling of RS485.",
      "Allows long, robust sensor buses with many devices.",
      "A/B twisted pair, daisy chain, termination at the two ends only, one bias point. Isolated adapters protect the Pi from ground faults.",
      "Mount in the cabinet, keep the USB cable short and strain-relieved.",
      "Add a bus in Advanced → Hardware with the adapter's port and the devices' baud/parity.",
      "Not applicable.",
      ["No devices answer: A/B swapped, wrong baud/parity, missing termination.", "Intermittent: missing bias, noise, stubs too long.", "Port vanishes: USB glitch; use a good cable and powered hub if needed."],
      "Check connectors and enclosure for moisture.", "Long-lived; replace on faults."),
    C("enclosures", "Enclosures",
      "Protect electronics from water, dust and tampering.",
      "Rated boxes with seals; the IP code gives protection against solids and water (IP65/IP66 for greenhouse splash).",
      "Greenhouses are humid and wet.",
      "Cable glands at the bottom, drip loops, DIN rail inside, earth bonding of metal parts by the electrician.",
      "Mount upright, out of direct spray where possible, with ventilation or a breather for condensation, leave working space.",
      "Not applicable.", "Not applicable.",
      ["Condensation inside: no breather, unsealed glands.", "Overheating: no ventilation in sun."],
      "Check seals and glands, remove condensation, clean filters.", "Seals harden over years: replace when cracked."),
    C("connectors", "Connectors and terminals",
      "Join wires and devices reliably.",
      "Screw/spring terminals, ferrules, M12 and other waterproof connectors.",
      "Most field faults are connection faults.",
      "Use ferrules on stranded wire, keep pairs together for RS485, use IP67 connectors outdoors, and label everything.",
      "Torque terminals as specified; use strain relief.",
      "Not applicable.", "Not applicable.",
      ["Intermittent faults: loose or corroded terminals.", "Moisture in connectors: wrong IP rating or missing seals."],
      "Re-check tightness after the first weeks and yearly; replace corroded parts.", "Replace when corroded or loose."),
    C("cables", "Cables",
      "Carry power and signals.",
      "Copper conductors with insulation; shielded twisted pair for RS485; larger cross-sections for DC loads.",
      "Voltage drop and noise cause many problems.",
      "RS485: shielded twisted pair, shield earthed at one end. DC loads: size for voltage drop (Planner calculator) AND current rating (electrician).",
      "Use UV-resistant cable outdoors, ducts or conduit, support runs, separate mains from signal cables.",
      "Not applicable.", "Not applicable.",
      ["Voltage drop at far loads: cable too thin or long.", "Noise on RS485: unshielded, parallel to mains."],
      "Inspect for damage, UV ageing and rodent damage.", "Replace when insulation is cracked or damaged."),
    C("safety", "Safety equipment",
      "Hardware that keeps people and equipment safe independently of the software.",
      "Emergency stops, RCDs, breakers, surge protection, thermal cut-outs, float switches, limit switches.",
      "Software can crash; protective devices must not depend on it.",
      "Installed by a qualified electrician. Heater over-temperature cut-outs and pump dry-run protection act in the load circuit.",
      "Accessible e-stops at entrances, labelled, tested; protective devices tested after installation and periodically.",
      "Commissioning checks in the application record that YOU tested them.",
      "Not applicable.",
      ["RCD trips: moisture or insulation fault: find the fault, do not bypass.", "E-stop does not cut power: wiring error: stop and fix before using the system."],
      "Test e-stops, RCDs and cut-outs on a schedule and after any change.", "Per manufacturer's instructions and local rules."),
]


def I(id_, cat, name, summary, iface, supply, external_power=False, adc=False, isolation=False, esp32="yes",
      specs=(), models=(), alternatives=(), driver=None, bom=(), notes=""):
    return dict(id=id_, category=cat, name=name, summary=summary, interface=list(iface), supply=supply,
                external_power=external_power, needs_adc=adc, needs_isolation=isolation, esp32=esp32,
                specs=[{"name": k, "value": v} for k, v in specs], models=list(models),
                alternatives=list(alternatives), driver=driver, bom_ids=list(bom), notes=notes)


M = lambda name, maker, note="": {"name": name, "maker": maker, "note": note}  # noqa: E731

ITEMS: list[dict] = [
    I("rpi5", "raspberry_pi", "Raspberry Pi 5", "Faster Raspberry Pi with a PCIe connector for NVMe storage.", ["gpio", "i2c", "1wire", "uart", "spi"],
      "5 V USB-C (official supply is 5 V / 5 A class)", True, esp32="n/a",
      specs=[("CPU", "Quad-core Arm Cortex-A76"), ("RAM options", "Include 4 GB and 8 GB"), ("Storage", "microSD; PCIe connector for NVMe"), ("GPIO", "40-pin header, 3.3 V logic"), ("Analogue inputs", "None")],
      models=[M("Raspberry Pi 5 4GB", "Raspberry Pi Ltd", "Recommended starting point in the Planner")], alternatives=["Raspberry Pi 4 Model B", "Industrial Raspberry-Pi-based controllers"],
      bom=("pi5_4gb", "pi_psu", "pi_cooler"), notes="The Pi 5 has no always-on power from the header for a UPS HAT; check power options for your setup."),
    I("rpi4", "raspberry_pi", "Raspberry Pi 4 Model B", "Capable and lower-cost; fully sufficient for this software.", ["gpio", "i2c", "1wire", "uart", "spi"],
      "5 V USB-C (3 A supply recommended)", True, esp32="n/a",
      specs=[("CPU", "Quad-core Arm Cortex-A72"), ("RAM options", "1 GB to 8 GB"), ("Storage", "microSD; USB boot"), ("Analogue inputs", "None")],
      models=[M("Raspberry Pi 4 Model B 4GB", "Raspberry Pi Ltd")], alternatives=["Raspberry Pi 5"]),
    I("esp32_devkit", "esp32", "ESP32 development board", "Wi-Fi microcontroller board for remote I/O nodes.", ["i2c", "spi", "uart", "gpio", "wifi_mqtt"],
      "5 V USB or regulated supply", True, esp32="n/a", specs=[("Logic level", "3.3 V"), ("Connectivity", "Wi-Fi and Bluetooth"), ("ADC", "On-chip, non-linear: use an external ADC for measurements")],
      models=[M("ESP32 DevKit-type boards", "Espressif (module maker); many board vendors", "Choose a board with a reputable regulator")], bom=("esp32",),
      notes="Not supported by this application yet."),
    I("ds18b20", "temperature", "DS18B20 waterproof temperature probe", "Digital temperature probe for nutrient solution, water and soil.", ["1wire"],
      "3.0-5.5 V from the Pi 3.3 V pin, with 4.7 kΩ pull-up", False,
      specs=[("Interface", "1-Wire, unique 64-bit ID (family code 28)"), ("Range", "-55 to +125 °C"), ("Accuracy", "±0.5 °C from -10 to +85 °C"), ("Resolution", "9 to 12 bit"), ("Power-on value", "85.0 °C (the driver rejects it)")],
      models=[M("DS18B20", "Analog Devices (Maxim)", "Waterproof stainless-steel probe versions are common")], alternatives=["RS485 temperature transmitter for long runs"],
      driver="ds18b20", bom=("ds18b20",), notes=SPEC_NOTE),
    I("sht3x", "humidity", "Sensirion SHT3x (SHT31/SHT35) temperature and humidity", "I2C temperature/humidity sensor for air.", ["i2c"], "2.15-5.5 V (3.3 V from the Pi)", False,
      specs=[("Interface", "I2C, address 0x44 or 0x45 (ADDR pin)"), ("SHT31 typical accuracy", "±2 %RH, ±0.2 °C"), ("SHT35 typical accuracy", "±1.5 %RH, ±0.1 °C"), ("CRC", "8-bit CRC on every value (checked by the driver)")],
      models=[M("SHT35 (probe or breakout)", "Sensirion"), M("SHT31", "Sensirion")], alternatives=["RS485 temperature/humidity transmitter"],
      driver="sht3x", bom=("sht35",), notes=SPEC_NOTE),
    I("soil_probe_rs485", "soil_moisture", "RS485 soil probe (moisture/temperature/EC)", "Industrial soil probe with Modbus output.", ["rs485"], "Typically 5-30 V DC, per datasheet", True,
      models=[M("Several vendors", "-", "Verify the register map in the datasheet; this application ships none")], alternatives=["Analogue capacitive probe + ADC (indicator only)"],
      driver="modbus_rtu", bom=("soil_probe",)),
    I("soil_probe_analog", "soil_moisture", "Analogue capacitive soil probe", "Low-cost probe with a voltage output.", ["analog_voltage"], "3.3-5 V from the controller", False, adc=True,
      models=[M("Hobby capacitive probes", "-", "Indicator only; calibrate in your soil")], alternatives=["RS485 soil probe"],
      notes="The Raspberry Pi has no analogue inputs: add an external I2C ADC."),
    I("scd41", "co2", "Sensirion SCD41 CO2 sensor", "Photoacoustic CO2 sensor with temperature and humidity.", ["i2c"], "2.4-5.5 V", False,
      specs=[("Interface", "I2C, address 0x62"), ("Measurement range", "400-5000 ppm (specified)"), ("Accuracy", "±(40 ppm + 5 % of reading), typical")],
      models=[M("SCD41", "Sensirion")], alternatives=["Industrial NDIR RS485 transmitter"], bom=("co2",), notes=SPEC_NOTE + " No dedicated driver in this application yet."),
    I("ndir_rs485", "co2", "Industrial NDIR CO2 transmitter (RS485)", "Robust CO2 transmitter for continuous use.", ["rs485"], "Typically 12-24 V DC, per datasheet", True,
      models=[M("Several vendors", "-", "Verify the register map")], alternatives=["SCD41"], driver="modbus_rtu", bom=("co2",)),
    I("lux_sensor", "light", "Illuminance (lux) sensor", "Measures light as the human eye sees it.", ["i2c", "analog_voltage"], "3.3 V", False,
      models=[M("Digital I2C lux sensors", "-")], alternatives=["PAR sensor (correct for plants)"], notes="Not a substitute for PAR: lux and PPFD are not interchangeable."),
    I("led_grow_light", "light", "LED grow light", "Horticultural LED fixture for supplemental light.", ["power_ac"], "230 V AC (or DC for some models)", True, esp32="no",
      models=[M("Horticultural LED fixtures", "-", "Compare PPF (µmol/s) and efficacy from datasheets, not lumens")], notes="Switched through a rated contactor by an electrician.", bom=("led",)),
    I("par_rs485", "par", "RS485 PAR (quantum) sensor", "Measures PPFD for DLI and lighting control.", ["rs485"], "Typically 12-24 V DC, per datasheet", True,
      models=[M("Several vendors", "-", "Verify register map and spectral response")], alternatives=["Analogue quantum sensor + isolated ADC"], driver="modbus_rtu", bom=("par",)),
    I("ph_transmitter", "ph", "pH probe with RS485 transmitter", "Continuous pH measurement for nutrient solution.", ["rs485", "analog_420ma"], "Typically 12-24 V DC", True, isolation=True,
      models=[M("Several vendors", "-", "Verify the register map; prefer isolated transmitters")], driver="modbus_rtu", bom=("ph_probe",)),
    I("ec_transmitter", "ec", "EC probe with RS485 transmitter", "Continuous EC measurement.", ["rs485", "analog_420ma"], "Typically 12-24 V DC", True, isolation=True,
      models=[M("Several vendors", "-", "Verify the register map")], driver="modbus_rtu", bom=("ec_probe",)),
    I("float_switch", "water_level", "Float switch", "Detects a high or low water level with a dry contact.", ["gpio_in", "contact"], "None (passive contact)", False,
      models=[M("Vertical or side-mount float switches", "-")], driver="gpio_input", bom=("float_sw",),
      notes="For protection, wire a float switch in series with the pump control circuit as well as reading it in software."),
    I("level_continuous", "water_level", "Continuous level sensor (ultrasonic/pressure)", "Measures tank level continuously.", ["rs485", "analog_420ma"], "Typically 12-24 V DC", True,
      models=[M("Ultrasonic or submersible pressure transmitters", "-")], driver="modbus_rtu", bom=("tank_level",)),
    I("flow_pulse", "flow", "Pulse flow meter", "Outputs pulses proportional to volume.", ["pulse"], "5-24 V typical, per datasheet", True, isolation=True,
      models=[M("Turbine/paddle flow meters", "-")], bom=("flow_meter",), notes="Pulse counting inputs are not implemented yet."),
    I("flow_modbus", "flow", "Modbus flow meter", "Reports flow and volume over RS485.", ["rs485"], "Typically 12-24 V DC", True, models=[M("Several vendors", "-")], driver="modbus_rtu", bom=("flow_meter",)),
    I("irrigation_pump", "pumps", "Irrigation pump", "Pressurises the irrigation system.", ["power_ac", "power_dc"], "230 V AC or 12/24 V DC, per model", True, esp32="no",
      models=[M("Centrifugal, multistage or diaphragm pumps", "-", "Select from the pump curve")], bom=("pump",)),
    I("dosing_pump", "pumps", "Peristaltic dosing pump", "Doses nutrient and pH concentrates.", ["power_dc"], "12/24 V DC typical", True, esp32="no",
      models=[M("Peristaltic dosing pumps", "-")], bom=("dosing",), notes="Dosing control loops are not implemented yet."),
    I("solenoid_24vdc", "valves", "24 V DC solenoid valve", "Zone valve, normally closed.", ["power_dc"], "24 V DC", True, esp32="no",
      models=[M("Irrigation solenoid valves", "-", "Check pressure range and coil type")], bom=("valves",)),
    I("exhaust_fan", "fans", "Exhaust fan", "Ventilation fan, typically mains-powered.", ["power_ac"], "230 V AC (or DC)", True, esp32="no",
      models=[M("Axial or centrifugal exhaust fans", "-", "Use datasheet free-air airflow and derate")], bom=("exhaust_fan",)),
    I("circulation_fan", "fans", "Circulation (HAF) fan", "Mixes air inside the crop.", ["power_ac", "power_dc"], "230 V AC or DC", True, esp32="no",
      models=[M("Horizontal airflow fans", "-")], bom=("circ_fan",)),
    I("window_actuator", "actuators", "Window actuator / rack motor", "Moves a vent window or screen.", ["power_dc"], "12/24 V DC typical", True, esp32="no",
      models=[M("Linear actuators and rack-and-pinion motors", "-", "With end limit switches")], bom=("vent_act",)),
    I("modbus_relay_board", "relays", "Modbus relay board", "Relay outputs controlled over RS485.", ["rs485"], "Typically 12-24 V DC", True, isolation=False,
      models=[M("Several vendors", "-", "Verify coil numbers in the datasheet")], driver="modbus_coil"),
    I("din_contactor", "relays", "DIN-rail contactor", "Switches mains loads under control of a low-voltage coil.", ["power_ac"], "Coil 24 V DC/AC, per model", True, esp32="no",
      models=[M("Installation contactors", "-")], bom=("relay_ind", "light_ctrl"), notes="Installed by a qualified electrician."),
    I("mosfet_driver_24v", "mosfet", "Isolated 24 V DC MOSFET driver", "Switches valves and small DC loads from GPIO.", ["gpio_out"], "Load supply 24 V DC (logic from GPIO)", True, isolation=False,
      models=[M("Opto-isolated MOSFET modules", "-")], driver="gpio_output", bom=("mosfet",)),
    I("psu_24v_din", "power_supplies", "24 V DIN-rail power supply", "Main DC supply for actuators.", ["power_ac"], "Mains in, 24 V DC out", True, esp32="no",
      models=[M("MDR-20-24 / SDR-75-24 class", "MEAN WELL", "Product pages exist on a Romanian distributor; check specs and price live"), M("TRACOPOWER DIN-rail 24 V", "TRACO POWER")],
      bom=("psu24",), notes="Mains side installed by an electrician."),
    I("psu_5v_pi", "power_supplies", "Raspberry Pi power supply", "Clean 5 V supply for the controller.", ["power_ac"], "Mains in, 5 V USB-C out", True, esp32="no",
      models=[M("Official Raspberry Pi USB-C supplies", "Raspberry Pi Ltd")], bom=("pi_psu",)),
    I("dc_ups", "ups", "DC UPS / shutdown module", "Short-term battery backup for the controller.", ["power_dc"], "Battery-backed 5 V/12 V output", True, esp32="no",
      models=[M("DC UPS modules for single-board computers", "-")], bom=("ups",), notes="Shutdown signalling not yet integrated."),
    I("usb_rs485", "rs485_adapters", "USB to RS485 adapter", "Connects the Pi to the RS485 bus.", ["uart", "rs485"], "Powered from USB", False, esp32="n/a",
      models=[M("Industrial isolated adapters", "-", "Prefer isolation and ESD protection")], bom=("rs485_adapter",)),
    I("enclosure_ip65", "enclosures", "IP65/IP66 enclosure", "Protects electronics in a humid greenhouse.", ["none"], "-", False, esp32="n/a",
      models=[M("Polycarbonate or ABS IP65/IP66 boxes", "-")], bom=("encl_ip65", "pi_enclosure")),
    I("connectors_ip67", "connectors", "Waterproof connectors and terminals", "M12-type and terminal blocks.", ["none"], "-", False, esp32="n/a",
      models=[M("M12 connectors, ferrules, DIN terminals", "-")], bom=("connectors", "terminals", "glands")),
    I("cable_rs485", "cables", "Shielded twisted-pair cable for RS485", "Signal cable for the RS485 bus.", ["none"], "-", False, esp32="n/a",
      models=[M("Shielded twisted pair (e.g. RS485/data cable)", "-")], bom=("rs485_cable",)),
    I("cable_dc", "cables", "DC power cable", "Cable for 24 V loads, sized for voltage drop and current.", ["none"], "-", False, esp32="n/a",
      models=[M("Multicore or single-core flexible cable", "-")], notes="Use the Planner voltage-drop calculator; current rating is for the electrician."),
    I("estop_button", "safety", "Emergency stop pushbutton", "Hardware stop that removes actuator power.", ["contact"], "In the control circuit", False, esp32="no",
      models=[M("Latching e-stop pushbuttons", "-")], bom=("estop",), notes="The software e-stop is not a substitute."),
    I("rcd_breaker", "safety", "RCD and circuit breakers", "Protection against earth faults and overload.", ["power_ac"], "Mains", True, esp32="no",
      models=[M("RCD / MCB per electrician's design", "-")], bom=("mcb_rcd",), notes="Selected and installed by a qualified electrician."),
    I("heater_cutout", "safety", "Heater over-temperature cut-out", "Independent thermal protection for heaters.", ["contact"], "In the heater circuit", False, esp32="no",
      models=[M("Manual-reset thermal cut-outs", "-")], notes="Must work with the controller powered off."),
    I("surge_protector", "safety", "Surge protection device", "Limits damage from voltage spikes.", ["power_ac"], "Mains", True, esp32="no",
      models=[M("DIN-rail SPDs", "-")], bom=("spd",)),
]

CAT_BY_ID = {c["id"]: c for c in CATEGORIES}
ITEM_BY_ID = {i["id"]: i for i in ITEMS}

PAGE_SECTIONS = ["what", "how", "why", "wiring", "installation", "configuration", "calibration", "troubleshooting", "maintenance"]


def page(item_id: str) -> dict | None:
    it = ITEM_BY_ID.get(item_id)
    if it is None:
        return None
    cat = CAT_BY_ID[it["category"]]
    return {**{k: it[k] for k in ("id", "name", "summary", "interface", "supply", "specs", "models", "alternatives", "driver", "bom_ids", "notes")},
            "category": {"id": cat["id"], "title": cat["title"]},
            "sections": {s: cat[s] for s in PAGE_SECTIONS}, "replacement": cat["replacement"],
            "spec_note": SPEC_NOTE if it["specs"] else "No specification figures are given: they depend on the exact product, so use its datasheet."}


# --------------------------------------------------------- compatibility

IFACE_TEXT = {
    "i2c": "I2C", "1wire": "1-Wire", "uart": "UART / serial", "spi": "SPI", "gpio": "GPIO", "gpio_in": "digital input (GPIO)", "gpio_out": "digital output (GPIO)",
    "rs485": "RS485 / Modbus RTU", "analog_voltage": "analogue voltage", "analog_420ma": "4-20 mA current loop", "pulse": "pulse output",
    "wifi_mqtt": "Wi-Fi / MQTT", "contact": "dry contact", "power_ac": "mains power", "power_dc": "DC power", "none": "no data connection",
}


def compat(item: dict) -> dict:
    """Plain answers to: can it connect to the Raspberry Pi / ESP32, does it need an ADC, what protocol, what supply?"""
    ifs = item["interface"]
    adapters: list[str] = []
    warnings: list[str] = []
    pi = "directly"
    data_ifs = [i for i in ifs if i not in ("power_ac", "power_dc", "none")]
    if not data_ifs:
        pi = "not_applicable"
        warnings.append("This item has no data connection: the Pi cannot talk to it. It is powered and/or switched through a driver, relay or contactor.")
    elif "i2c" in ifs or "1wire" in ifs or "spi" in ifs or "uart" in ifs or "gpio" in ifs:
        pi = "directly"
    elif "rs485" in ifs:
        pi = "with_adapter"
        adapters.append("USB-RS485 adapter (isolated preferred)")
    elif "analog_voltage" in ifs:
        pi = "with_adapter"
        adapters.append("External I2C ADC (the Pi has no analogue inputs); keep signals within 0-3.3 V")
    elif "analog_420ma" in ifs:
        pi = "with_adapter"
        adapters.append("4-20 mA receiver (precision shunt + isolated ADC) or an RS485 variant of the transmitter")
    elif "pulse" in ifs:
        pi = "with_adapter"
        adapters.append("Level shifter / opto-isolator into a GPIO input (5 V and 24 V pulses must not reach a Pi pin)")
    elif "gpio_in" in ifs or "contact" in ifs:
        pi = "directly"
    elif "gpio_out" in ifs:
        pi = "with_adapter"
        adapters.append("Isolated driver module (already part of this item) between the GPIO and the load")
    if "gpio_in" in ifs or "contact" in ifs:
        warnings.append("Dry contact: use a pull-up and debounce; for signals above 3.3 V use opto-isolation.")
    if "gpio_out" in ifs:
        warnings.append("GPIO is 3.3 V logic with a few mA of drive: never connect a load, relay coil or mains device directly.")
    if "i2c" in ifs:
        warnings.append("I2C is for short cables (tens of centimetres). For longer distances use an RS485 variant or an ESP32 node.")
    if "1wire" in ifs:
        warnings.append("1-Wire needs a 4.7 kΩ pull-up to 3.3 V; keep stubs short.")
    if "power_ac" in ifs:
        warnings.append("Mains voltage: switch only through suitably rated contactors installed by a qualified electrician; never use hobby relay boards or GPIO.")
    needs_adc = bool(item["needs_adc"] or "analog_voltage" in ifs or ("analog_420ma" in ifs and "rs485" not in ifs))
    esp = item["esp32"]
    if esp == "yes":
        esp_txt = ("yes" if "i2c" in ifs or "1wire" in ifs or "spi" in ifs or "uart" in ifs else
                   "yes, with a RS485 transceiver" if "rs485" in ifs else "yes, with an external ADC" if needs_adc else "yes")
    else:
        esp_txt = {"n/a": "not applicable", "no": "no (it is a power/mains item: switch it through a driver)"}.get(esp, esp)
    from app.hal.registry import DRIVERS
    drv = DRIVERS.get(item["driver"]) if item["driver"] else None
    outs = None
    if item["driver"] and drv is None:
        from app.hal.outputs import OUTPUT_DRIVERS
        outs = OUTPUT_DRIVERS.get(item["driver"])
    d = drv or outs
    return {
        "item": item["id"], "name": item["name"],
        "protocols": [IFACE_TEXT.get(i, i) for i in ifs],
        "can_connect_to_pi": pi, "adapters_needed": adapters, "needs_adc": needs_adc,
        "needs_external_power": bool(item["external_power"]), "supply": item["supply"],
        "esp32": esp_txt, "warnings": warnings,
        "supported_by_application": None if d is None else {"driver": item["driver"], "hardware_tested": bool(getattr(d, "hardware_tested", False))},
        "summary": _summary(item, pi, adapters, needs_adc, d),
    }


def _summary(item, pi, adapters, needs_adc, d) -> str:
    parts = {"directly": "Connects directly to the Raspberry Pi", "with_adapter": "Needs an adapter to connect to the Raspberry Pi",
             "not_applicable": "No data connection to the Raspberry Pi"}[pi]
    if adapters:
        parts += f" ({'; '.join(adapters)})"
    parts += ". " + ("Needs an ADC. " if needs_adc else "No ADC needed. ")
    parts += ("Supported by a driver in this application" + ("" if getattr(d, "hardware_tested", False) else " (not yet tested on hardware)") + "." if d is not None
              else "No driver for it in this application yet." if item["interface"] and item["interface"][0] not in ("none", "power_ac", "power_dc") else "")
    return parts.strip()


def custom_compat(interface: list[str], supply: str = "", external_power: bool = False, needs_adc: bool = False, esp32: str = "yes") -> dict:
    """Same answers for hardware that is not in the encyclopedia."""
    item = {"id": "custom", "name": "Your device", "interface": interface, "supply": supply or "unspecified", "external_power": external_power,
            "needs_adc": needs_adc, "needs_isolation": False, "esp32": esp32, "driver": None}
    return compat(item)
