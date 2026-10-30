# Testing

## Run everything

```bash
cd backend
.venv/Scripts/python -m pytest -q          # Linux/Pi: .venv/bin/python
cd ../frontend && npm run build            # TypeScript type-check + production build
```

Last full run (development PC): **284 backend tests passed** (about 90 s), lint (`ruff`) clean, `pip-audit` and `npm audit` without findings. The frontend is verified by the TypeScript compiler and manual/browser checks; it has **no automated UI tests**.

## What the tests cover

| Area | File(s) | Count | Highlights |
|---|---|---|---|
| Drivers and bus protocols | test_modbus, test_hardware_api, test_ingest | 24 | CRC vectors, framing, timeouts, exceptions, 1-Wire/I2C emulation, calibration, scan, conflicts |
| Irrigation engine and interlocks | test_irrigation | 29 | sequencing, dry run, burst, tank low/stale, runtime ceiling, e-stop persistence, failed ON/OFF, gating |
| Climate engine | test_climate_rules, test_climate_engine | 45 | hysteresis, timing, priorities, interlocks, windows (homing, limits, hazards), lighting/DLI |
| Planner, shopping, wiring | test_planner | 17 | sizing maths, no invented prices, exports, diagrams |
| Knowledge, analytics, map | test_knowledge, test_analytics, test_layout, test_climate | 29 | profile overrides, DLI coverage, reports, layout validation |
| Encyclopedia, wizard, manual | test_encyclopedia, test_wizard_manual | 22 | no prices in static data, state-driven steps, manual reflects real config |
| Maintenance and diagnostics | test_maintenance, test_diagnostics | 44 | due status, 30+ real messages explained, live diagnosis |
| **Security** | test_security | 24 | first-run code, login, lockout, CSRF, roles, **every route classified**, sessions, audit, headers, limits |
| **Backup and restore** | test_backup | 16 | consistency, corruption refused, traversal, round trip, undo, running jobs, schedule, alerts, audit continuity |
| **Roll-ups and performance** | test_rollup_perf | 11 | whole-hour pruning, history fallback, SQL bucketing speed, gate memo |
| **Smoke** | test_smoke_routes | 13 | every parameter-free GET answers; all routers documented |

Tests use emulated buses, simulated outputs and an injectable clock. They create real SQLite databases in temporary folders; nothing touches your data.

## What is not tested (be honest about it)

- **No real hardware**: no RS485 line, I2C/1-Wire sensor, GPIO pin, relay, pump, valve or window motor has ever been driven by this code. Every driver is flagged `hardware_tested: false`.
- **Not run on a Raspberry Pi** (Windows only so far); the systemd unit and `install.sh` were only syntax-checked; the Dockerfile was never built.
- Browser UI: no automated tests; checked by hand in a browser on desktop width (not phone), including a CSP check and a drag in the map designer.
- Security: no independent review, no penetration test, no fuzzing beyond the route-inventory tests.
- Long-running behaviour (days of operation, memory growth, clock changes) and power-loss recovery are not tested.
- Concurrency stress (many simultaneous users) is not tested.
- Crop profile contents, encyclopedia specifications and maintenance intervals are guidance, not verified data.

## Production-style runs

- `scripts/soak_test.py [seconds]` starts REAL server processes: a fresh real-mode install (nothing seeded, first-run setup), a demo soak (memory, CPU, endpoint latency, a zone run, the e-stop) and a **hard kill followed by a restart** (database intact, e-stop latched, backup verification passes). 19 checks; passed on the development PC.
- `scripts/benchmark.py [days]` measures data-heavy operations (PERFORMANCE.md). Run both on the Raspberry Pi: no Pi numbers exist yet.

## Commissioning is part of the test plan

For a real installation the **commissioning checklist** (Irrigation page → Commissioning checklist) is the acceptance test: software tests for interlock logic, data, database and backup, plus physical tests you perform and attest (e-stop, float switch, outputs, heater protection, window limits, restart, watchdog). Automatic control stays blocked until it passes.
