# Setting up the entire system, start to finish

This is the order to do things in, with a pointer to the detailed guide for each step. The application's **Setup guide** page tracks the same steps and ticks them off from your real system. Allow weeks, not hours: ordering parts, wiring, calibrating and commissioning take time.

> Mains wiring is for a qualified electrician. Never connect mains voltage to Raspberry Pi GPIO or to hobby relay boards. Everything below that touches equipment is **untested on real hardware**: work supervised and read [SAFETY.md](SAFETY.md) and [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) first.

## 1. Try it without any hardware (30 minutes, on any computer)

Install it on your PC (README: *Run it*), start with the demo data, and click through every page. Nothing is connected; all values are simulated and say so. Press the emergency stop, run a zone, open the Setup guide and the Encyclopedia, generate a manual. This tells you whether the application suits you before you spend money.

## 2. Describe your greenhouse and plan the hardware

1. **Greenhouse** page: dimensions, growing methods, and the engineering details the application will not guess: gutter and ridge height, orientation, covering, heating need, water pressure, electricity supply, location.
2. **Planner** page: enter datasheet values for the equipment you are considering (fan airflow, pump flow, dripper flow and spacing, drip line length, lighting targets, electrical loads). Quantities appear only when their inputs exist.
3. **Shopping** page and [HARDWARE_LIST.md](HARDWARE_LIST.md): choose low / recommended / professional, research suppliers, record **offers** (price, URL, availability; mark "verified" only if read on the live page). See [SHOPPING_LIST.md](SHOPPING_LIST.md) and [BUDGET.md](BUDGET.md). Tick items as you buy them. Use the **Encyclopedia** compatibility checker for anything you are unsure about.
4. Have the **electrician** design the mains side (breakers, RCD, surge protection, earthing, contactors, hardware e-stop) using the Wiring page's power diagram and the electrical loads you entered.

## 3. Prepare the Raspberry Pi

Follow [RASPBERRY_PI_SETUP.md](RASPBERRY_PI_SETUP.md): Raspberry Pi OS 64-bit via Raspberry Pi Imager (hostname, user, SSH), Ethernet, fixed address (router reservation), updates, **time zone and clock**, I2C / 1-Wire as needed. Use a high-endurance card or an SSD, a proper power supply and a ventilated IP-rated enclosure.

## 4. Install the software

[INSTALLATION.md](INSTALLATION.md): download the release archive (or build from source), extract it on the Pi, `sudo ./deploy/install.sh`. Open `http://<pi-address>:8000`, create the administrator with the one-time code from `/var/lib/greenhouse/setup_code.txt`, create operator/viewer accounts for other people. Keep it on a private network or add HTTPS ([SECURITY.md](SECURITY.md)). On the **Admin** page set the daily backup, choose a **copy folder on a USB drive**, press *Test backup and restore*.

Start on a **fresh database with `GCC_SIMULATE=false`** (the service file does this) so no demo equipment exists.

## 5. Build the cabinet and wire the sensors (power OFF while wiring)

Use the personalised **Manual** page after registering devices; until then the sequence is:

1. Mount the cabinet, DIN rail, 24 V supply with a fuse per feeder, the Pi with its supply, the USB-RS485 adapter. Electrician installs the mains side and hardware protections and tests them **before anything else is connected**.
2. **RS485 sensors** ([MODBUS_SETUP.md](MODBUS_SETUP.md)): daisy-chain twisted pair, termination at the two ends only, one bias point, shield earthed at one end, unique slave addresses.
3. **I2C and 1-Wire sensors** ([SENSOR_GUIDE.md](SENSOR_GUIDE.md)): short I2C cables, 4.7 kΩ pull-up for 1-Wire.
4. Register the buses and every sensor on **Hardware** (advanced mode), press **Test** on each, compare with a reference instrument, and **calibrate** pH, EC, soil probes and anything that needs it ([CALIBRATION_GUIDE.md](CALIBRATION_GUIDE.md)). Check the **Wiring** page's Modbus address table against your cable labels.

## 6. Water system and outputs

1. Install tank, pump, filter, valves, pipes. **Fit a float switch in the pump circuit as a hardware cut-out** (and a second sensor for the software to read).
2. **Irrigation → Setup**: register each output (with its maximum runtime), tanks (level and/or float sensor), zones (valve, pump, tank, flow sensor, limits, schedule). Drive GPIO outputs only through isolated driver modules; Modbus relay boards use the `modbus_coil` driver ([IRRIGATION_GUIDE.md](IRRIGATION_GUIDE.md)).
3. **Climate → Setup**: fans, heaters (each needs a software safety limit **and** a hardware over-temperature cut-out), CO₂ (only with independent shut-off and alarm), window motors (with limit switches), lights ([VENTILATION_GUIDE.md](VENTILATION_GUIDE.md)).
4. With the **water/heat source harmless** (pump dry-run protection in place, heater disconnected), switch each output by hand from the Irrigation/Climate pages and watch it.

## 7. Rules, schedules, crops

Define rules (or generate them from setpoints you choose; the **Plants** page can suggest starting values from a crop profile), irrigation schedules and moisture triggers, lighting programs. Record your crop batches. Review the **Map** and place sensors. Leave automatic control **off** for now.

## 8. Maintenance and documentation

**Maintenance** page → *Create from my equipment* and adjust intervals; check **System health**. Generate the **Manual** (PDF/HTML) and the printable checklist and keep a printed copy in the cabinet ([MAINTENANCE.md](MAINTENANCE.md)).

## 9. Commissioning

Irrigation page → **Commissioning checklist**: run the software tests, then perform and attest each physical test (hardware e-stop, float switch, outputs, heater/CO₂ protection, window limits, restart behaviour, watchdog). Any change to outputs, tanks or zone wiring reopens the affected checks.

## 10. Going live

Work through the checklist in [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md), including the supervised trial. Only then switch on automatic irrigation and climate control (each has its own master switch). Keep watching alerts, the health page and the first weeks of reports ([TROUBLESHOOTING.md](TROUBLESHOOTING.md) when something looks wrong).
