# Irrigation guide

Implemented in `backend/app/automation` (engine, interlock rules) and the **Irrigation** page. Tested with simulated outputs and an emulated Modbus relay; **no output driver has been tested on physical hardware**. Treat the first real commissioning as a supervised test.

## Concepts

- **Output:** a pump, valve, dosing pump or other switched device, with a *mandatory maximum runtime*. The engine switches it off at that limit no matter what asked for it.
- **Tank:** a water source with a level sensor and/or a float-switch sensor (value 1 = water present) and a minimum level.
- **Zone:** one valve (+ optionally a pump, a tank, a flow sensor) with maximum duration, minimum interval between runs, optional flow alarm limits, optional schedule and moisture trigger. A zone with a pump must name a tank.

## Output drivers

| Driver | Use | Notes |
|---|---|---|
| `simulated_output` | demo, tests | wired to a simulated plant (flow, tank level) |
| `gpio_output` | Pi GPIO through an isolated MOSFET/relay module | BCM 4-27 (2/3 reserved for I2C); GPIO is 3.3 V logic, never connect mains directly. Uses gpiozero |
| `modbus_coil` | RS485 relay boards | function 0x05, coil number from the board's datasheet, `active_high` option |
| sensors: `gpio_input` | float switches, feedback | `invert` so that 1 always means "OK" |

## The sequence

Valve opens → settle (default 3 s) → pump on → run → pump off → settle → valve closes. A fault switches everything off at once. A pump starts only while one of its zones' valves is open (dead-head protection), and shared pumps stay on while any of their zones runs.

## Software interlocks (second line of defence)

Everything uncertain means OFF: missing, stale (default >20 s) or low tank readings; no tank assigned; flow sensor stale; driver errors. During a run the engine stops it on: low tank, flow below/above your limits after a grace period (dry run, blockage, burst), feedback mismatch, maximum runtime, e-stop. Idle leak detection (optional) raises an alert when flow is seen with everything off. Flow limits are **yours**: the application invents none. Water volume is measured only when a zone has a flow sensor; otherwise only an estimate from your expected flow is shown, labelled as such.

Outputs are forced OFF at start-up and shutdown. The e-stop latch survives restarts and needs an explicit confirmed reset. A failed OFF command raises a critical alert and is retried; cut power manually if you see it.

**These interlocks do not replace hardware protection.** Install a float switch in the pump circuit, a hardware e-stop that cuts actuator power, and proper fuses/breakers (SAFETY.md). A crashed or powered-off Pi cannot protect anything.

## Manual vs automatic

Manual "Water now" and output switching work any time but still obey the interlocks and runtime limits. **Automatic irrigation** (schedules and moisture triggers) additionally needs: automation level not "monitor only", the master switch on (off by default), the zone's auto switch on, no e-stop, and a **passed commissioning checklist**. Missed schedule times (e.g. during an outage) are skipped, not caught up. Moisture triggers use all listed sensors and do nothing if any is stale.

## Commissioning

Advanced → Irrigation → Commissioning checklist (12 checks). Software tests verify the interlock logic and live data; physical checks (e-stop, float switch, outputs, restart, watchdog, backup) require you to perform the test and attest it with a note. Passes are bound to the equipment configuration: changing outputs, tanks or zone wiring invalidates them. A simulated float/level sensor combined with a real output blocks the gate.

## Not yet implemented

Pulse-counting flow meters (use a Modbus flow meter or a pulse-to-Modbus converter for now), hardware watchdog automation, fertigation/EC-pH dosing control loops, pressure-based protection, ESP32 outputs.
