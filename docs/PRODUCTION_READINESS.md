# Production readiness assessment (v0.9.0)

**Verdict: ready for a supervised pilot, not yet for unattended automatic control.**

You can install it, monitor sensors, keep records, plan and buy the hardware, and switch outputs by hand under supervision on a private network. Do **not** leave pumps, heaters, CO₂ or lights under unattended automatic control until you have completed the checklist at the bottom. The reason is simple: the control logic is thoroughly tested against simulated and emulated equipment, but **no real device has ever been driven by this code**, and a greenhouse can be damaged or endangered by a wiring or timing mistake that no simulation reveals.

## What was checked for this assessment

| Check | Result |
|---|---|
| Automated test suite | **284 tests pass** (`pytest`, about 90 s): drivers, interlocks, engines, rules, planner, analytics, security, backup/restore, roll-ups, smoke test of every GET endpoint |
| Lint (`ruff`: errors, unused code, bug patterns) | clean; code is also valid for Python 3.11 syntax (the version on current Raspberry Pi OS) |
| Dependency audit | `pip-audit`: no known vulnerabilities in `requirements.txt`; `npm audit --omit=dev`: 0 vulnerabilities (as of 2026-10-30) |
| Production-style run (`scripts/soak_test.py`) | fresh real-mode start seeds nothing; first-run setup; ~100 MB memory, ~1 % CPU of one core on the development PC; zone run + e-stop exercised; **hard kill → restart: database intact, e-stop still latched, data and backup verification OK**; no tracebacks in logs |
| Security review (self) | sign-in, roles with every route classified, CSRF, lockout, CSP, audit log, size limits; API docs endpoints disabled by default; rate-limiter memory bounded; see SECURITY.md |
| Fresh-install behaviour | empty install is quiet: no alerts other than "no sensor readings"; manual says "no real hardware registered" instead of printing generic wiring |
| Browser | pages checked under the Content-Security-Policy with no violations (desktop width) |

## Status by area

| Area | Status | Notes |
|---|---|---|
| Data collection, storage, charts, reports, backup/restore | **Ready for pilot** | Tested with emulated buses; hourly roll-ups and pruning keep storage bounded; backups verified |
| Access control | **Ready on a private network** | Plain HTTP unless you add TLS; no 2FA; no external review |
| Planner, shopping list, manuals, guides | **Ready** | Prices only where recorded; crop/encyclopedia data are guidance, not verified data |
| Sensor drivers (Modbus, DS18B20, SHT3x, GPIO in) | **Unproven on hardware** | Written from datasheets; flagged `hardware_tested: false`; test every sensor against a reference |
| Output drivers (GPIO, Modbus relay) | **Unproven on hardware** | Same flag; first use must be supervised |
| Interlocks, runtime limits, e-stop latch | **Logic tested, wiring untested** | Software is a second line of defence; hardware protections must exist and be tested independently |
| Automatic irrigation / climate / lighting | **Not recommended unattended yet** | Gated by the commissioning checklist, but the checklist relies on your honesty about physical tests |
| Raspberry Pi deployment (`install.sh`, systemd) | **Untested on a Pi** | Syntax-checked only; expect small fixes |
| ESP32 / MQTT nodes, SCD41, pulse flow meters, dosing, PID | **Not implemented** | Documented as such |
| Performance on a Pi | **Unknown** | Benchmarked on a PC only; run `scripts/benchmark.py` on the Pi |

## Known limitations that matter in operation

- Time zone: schedules, DLI and reports use the system's local time (set it on the Pi, RASPBERRY_PI_SETUP.md).
- Missed schedules (outage) are skipped, not caught up. After a power cut the system starts with all outputs OFF and the e-stop latch as it was.
- A silent sensor means "unsafe" to every interlock, so a dead probe stops irrigation by design.
- Window positions are estimated from motor run time unless you fit limit switches.
- Backups on the same SD card do not survive a dead card: set the copy folder and copy them off the Pi.
- Reports cover raw-data retention (default 90 days); older periods exist only as hourly roll-ups in history charts and the seasonal comparison.

## Checklist before enabling automatic control on a real greenhouse

1. Hardware protections installed and tested **with the Raspberry Pi switched off**: float switch in the pump circuit, hardware e-stop cutting actuator power, heater over-temperature cut-out, CO₂ shut-off and room alarm (if used), window limit switches, RCD/breakers/earthing by a qualified electrician.
2. Every sensor tested against a reference instrument, calibrated where needed, and every output switched manually and observed.
3. A **dry run with the water/heat sources disconnected or harmless** to watch the sequencing, then supervised real runs.
4. Commissioning checklist fully passed (it re-opens when you change equipment).
5. HTTPS or a trusted wired network; strong administrator password; off-device backup copy made **and a restore rehearsed** on a spare system.
6. Time zone and clock correct; UPS or clean-shutdown plan for the Pi.
7. **A supervised trial of at least a few weeks** with automatic control enabled but you watching, alert notifications noticed, before you rely on it while away.
8. A person who can reach the greenhouse quickly when an alert fires: there are no SMS/e-mail notifications yet.
