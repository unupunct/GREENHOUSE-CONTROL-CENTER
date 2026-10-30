# Ventilation, heating, cooling and lighting

Implemented in `backend/app/automation/climate.py` (engine) and `climate_rules.py` (pure logic), operated from the **Climate** page. Tested against simulated outputs and a live simulated run; **no output driver has been tested on physical hardware**. Commission supervised, and rely on hardware protection.

## Sizing first

Use the Planner page (ventilation section): fans are sized from air **volume** (needs gutter height, ideally ridge height), your target air changes per hour, and the **datasheet airflow of the fan you intend to buy**, derated for static pressure. It will not calculate with missing inputs. Final sizing also needs vent opening areas. Heating load is **not calculated** by this application yet.

## Outputs and kinds

`fan`, `heater`, `cooler`, `humidifier`, `dehumidifier`, `light`, `co2`, `other` (plain on/off outputs), and `motor` (window/screen motors; used only through windows). Every output has a mandatory **maximum runtime**; when it is reached the output is forced off, an alert is raised and the output stays blocked for at least 60 s (then rules may switch it on again). Continuous equipment needs a long ceiling (up to 7 days).

Per-output **interlocks** (JSON on the output):

| Key | Meaning |
|---|---|
| `requires_on` | outputs that must be on (e.g. heater requires a circulation fan); they can start in the same tick |
| `forbids_on` | outputs that must not be on together (heater vs cooler); the higher-priority request wins, a tie switches both off |
| `min_on_s` / `min_off_s` | anti short-cycling for contactors and compressors |
| `stop_if` | `{"sensor_id", "above"}` software safety limit; a missing/stale reading also stops the output |
| `windows_max_open_pct` | not allowed while any vent is open more than this (heater efficiency, CO₂) |

**Heaters and CO₂ outputs must have `stop_if`.** They also need independent hardware protection: a heater over-temperature cut-out, and for CO₂ an independent shut-off and a room CO₂ alarm. CO₂ enrichment can be dangerous to people; this is why it is gated, but it is your installation's responsibility.

## Motorised windows and screens

A window uses two `motor` outputs (open, close) that are never energised together, a full travel time, optional limit-switch sensors, and optional rain/wind interlocks. Position is **dead-reckoned from run time** (an estimate), corrected by limit switches; moves to 0% or 100% add 10% overdrive so the end is really reached. After a restart or a runtime cut the position is unknown, and the first move homes against the closed end. A vent with a configured rain or wind sensor that has no fresh reading is closed (fail-safe). With automatic control on, a window nobody asks to open is **closed**. Fit end-of-travel limit switches or motor protection in hardware.

## Rules (visual builder)

IF conditions (sensor value, VPD, time of day, months, another output's state; match all/any) THEN actions (switch an output, move a window to N%).

- **Hysteresis:** each sensor/VPD condition has a trigger value and a stop value, so it does not chatter. Stop must be at or beyond the trigger on the safe side (validated).
- **Timing:** start delay, stop delay, minimum on/off, maximum on-time with cool-down.
- **Priority:** 0-99, higher wins per output. Ties go to OFF (windows: to the more closed). 100 is reserved for lighting programs, manual overrides beat everything except interlocks.
- **Unknown inputs:** a stale or missing sensor never switches anything on; the rule releases (or holds, if you choose "hold").
- **Record / notify:** every activation is logged as an event; "notify" also raises an alert.
- **Setpoint template:** enter your own day/night heating, vent and fan setpoints and the rules are generated (replacing earlier generated rules). Nothing is assumed: missing setpoints generate nothing.

## Lighting programs

Photoperiod (fixed hours from a start time) or **DLI top-up**: inside the photoperiod window lights switch on when PPFD is below one value and off above another, and stop for the day once the target DLI is reached. DLI is the PAR sensor reading integrated over the local day (it includes your own fixtures' light, so set the off-above PPFD well above the on-below value). PPFD is photons, not lux. Optional power sensor → daily energy (kWh). Long gaps (outages) are not integrated. The light output's maximum runtime must cover the photoperiod (validated).

## When automatic control runs

Manual overrides always work (subject to interlocks). Rules, windows and lighting programs run only when: the climate master switch is on (off by default), the greenhouse automation level is not "monitor only", no e-stop, and **all applicable commissioning checks passed**. Heater/CO₂ hardware protection and window limit switches are checks that apply when such equipment exists.

## Not yet implemented

CO₂ enrichment control strategy beyond rules, humidity-specific templates, proportional (PID) control, heating-load calculation, shading by solar radiation, seasonal target sets as a first-class object (use month conditions), crop-specific targets (see the Plants page for starting values).
