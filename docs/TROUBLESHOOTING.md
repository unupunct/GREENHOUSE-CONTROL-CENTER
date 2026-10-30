# Troubleshooting

Start with the **Maintenance** page: *Troubleshooting assistant* diagnoses a specific sensor/output/zone/window against the live system and *Explain* translates error messages. This page lists common symptoms and where to look. Not all of it has been verified on a physical installation.

## Sensors

| Symptom | Likely causes | Look at |
|---|---|---|
| "no/partial response" on an RS485 sensor | wrong slave address, baud/parity, A/B swapped, unpowered, no termination | MODBUS_SETUP.md; Hardware → Scan |
| "CRC mismatch" | noise, duplicate slave addresses, baud/parity, termination | MODBUS_SETUP.md |
| "Modbus exception 2/1" | register/function wrong (0- vs 1-based numbering) | device datasheet |
| "cannot open COM/ttyUSB" | adapter unplugged, wrong port, no permission | `dialout` group; port list in Hardware |
| DS18B20 CRC error or 85 °C | missing 4.7 kΩ pull-up, cable, supply | SENSOR_GUIDE.md |
| SHT3x CRC / I2C error | cable too long, wiring, I2C not enabled, wrong address | `i2cdetect -y 1` |
| reading rejected "outside valid range" | sensor fault, wrong scale/calibration, range set too tight | Hardware → Test; CALIBRATION_GUIDE.md |
| value drifts or jumps | calibration, contact, fouling, noise | CALIBRATION_GUIDE.md |

## Irrigation

| Symptom | Likely causes |
|---|---|
| zone refuses to start: tank low / no fresh reading / no tank | level sensor value, stale sensor, zone without tank |
| pump will not start: "dead-head" | its valve is not open yet (it starts after the valve) |
| run stopped: flow below minimum | empty tank, air lock, blocked filter, limit set too high |
| run stopped: flow above maximum | burst/disconnected pipe, limit set too low |
| "forced off at its maximum runtime" | request longer than the output's limit |
| scheduled run did not happen | automatic irrigation off, zone auto off, commissioning not passed, outage (missed schedules are skipped) |
| "Cannot switch ... OFF" | cut power at the hardware and fix the driver/bus before anything else |

## Climate

| Symptom | Likely causes |
|---|---|
| rule active but output off | interlock reason shown on the Climate page: requires/forbids, min off time, safety limit, window open limit, cooldown |
| heater/CO₂ refused | safety sensor stale or above its limit |
| window will not move | e-stop, rain/wind hazard, motor output blocked after a forced stop, unknown position (it homes first) |
| window position drifts | dead reckoning: fully close once to re-home; add limit switches |
| lights turn off early | the light output's maximum runtime is shorter than the photoperiod |

## The system

| Symptom | Likely causes |
|---|---|
| page does not load | service stopped; frontend not built (INSTALLATION.md) |
| reboots, freezes | under-voltage, storage, overheating |
| wrong dates in reports | clock not synchronised (health shows it) |
| nothing runs automatically | e-stop, master switches, automation level "monitor only", commissioning (see the Setup guide) |

If anything looks unsafe: use the hardware emergency stop, find the cause, then restart.
