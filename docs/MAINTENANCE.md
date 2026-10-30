# Maintenance and diagnostics

Maintenance page (all modes): system health, schedule, troubleshooting assistant, communication diagnostics, replacement history.

## Schedule

Tasks have an interval in days; the clock starts at creation and restarts each time you press **Done** (with an optional note, kept in a log). Status: *ok*, *due soon* (within the smaller of 7 days or 20 % of the interval), *overdue*. An overdue task raises one alert (cleared when done). The check runs hourly and on demand.

**Create from my equipment** proposes tasks for your REAL (non-simulated) equipment: pH/EC probe calibration, soil-probe checks, CO₂/PAR/humidity/temperature checks, pump, valve, fan and window inspections, heater and CO₂ protection tests, float-switch tests, e-stop test, filter cleaning, backup restore test, storage check. **The intervals are starting suggestions, not manufacturer data**: adjust them to your equipment, water quality and manufacturers' instructions. Simulated equipment generates no tasks.

## System health

Storage, memory, CPU temperature, system clock, database integrity, sensor polling, sensors answering, battery (a sensor of kind `battery`), emergency stop, commissioning and maintenance. Thresholds (disk free, CPU warning/critical, memory, battery minimum) are assumptions you can change; the Raspberry Pi starts throttling around 80 °C. A critical storage, CPU, clock, database or battery state raises an alert, cleared when it recovers. Storage health beyond free space (card wear) is not measured.

## Communication diagnostics

Per sensor and per bus: successful and failed reads, last error, time since last success, last read duration. Counters live in memory since the last restart.

## Troubleshooting assistant

- **Diagnose** a sensor, output, irrigation zone or window: it checks the live system (enabled? simulated? fresh reading? last error? bus configured? e-stop? interlock refusals? blocked after a forced stop? tank state? weather hazard? recent events) and lists what is wrong and what to do next.
- **Explain** any message: the application's own error and alert texts (Modbus timeout/CRC/exception, serial port, 1-Wire and I2C errors, out-of-range readings, tank, flow, dead-head, runtime limits, e-stop, output failures, safety limits, interlocks, weather, leak, commissioning, database, maintenance) are translated into meaning, likely causes and what to check. Unknown messages are shown as unrecognised, not guessed at.

## Replacement history

Record each replaced sensor, output or other item with date, reason, and old/new item, so calibration and failure patterns can be reviewed later.

## Not implemented

Automatic storage-wear monitoring, automatic UPS shutdown, per-output runtime hours, notification by email/SMS, and verification of off-device backup copies.
