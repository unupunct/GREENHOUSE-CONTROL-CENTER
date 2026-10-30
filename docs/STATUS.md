# Project status

All 8 phases are complete. This file records what is implemented, what is verified and what is not.

Only features listed under "Implemented and tested" should be treated as working.

## Pre-release audit (v0.9.0)

A final review before publication found and fixed: lint leftovers; the API documentation endpoints being reachable without sign-in (now off by default); an unbounded login rate-limiter map; unbounded growth of the event, audit and resolved-alert tables (now pruned after 365 days); missing GPIO libraries in the installer; the time zone not being surfaced (health page and setup commands now cover it); a misleading "MQTT broker" label in the architecture diagram; development-phase wording in user-facing text; chart axis labels that collapsed on flat data. Added deep links (`#/page`), a pinned `requirements.lock`, `scripts/soak_test.py`, a release-archive builder and `docs/PRODUCTION_READINESS.md` (verdict: supervised pilot, not unattended automatic control). 284 tests pass.

## Phase 8 - Testing, security, performance, backup and recovery, complete documentation

**Implemented and tested** (281 backend tests passing; frontend builds; a live server run with authentication on: first-run setup through the UI, Mermaid/Map/Analytics/Admin pages under the Content-Security-Policy with no violations, backup, verify and restore on a running instance)
- Authentication and authorisation: one-time setup code, scrypt password hashes, server-side sessions in HttpOnly/SameSite=Strict cookies, three roles (viewer/operator/admin) with every route classified (a test fails if a new endpoint is not), lockout after failed sign-ins, CSRF header + origin check, request size limits, audit log, security headers/CSP, user management with last-admin protection, sign-in/setup/account/Admin pages
- Backup and restore: consistent online SQLite backups with integrity check, checksum and manifest, daily schedule, retention, optional copy to a USB/NAS folder, failure alerts, health indicator, download, restore (verify, safety copy, outputs off, engines reloaded, audit trail preserved), upload restore, automated round-trip verification that is now the **Backup and restore** commissioning check
- Performance: SQL bucketing for history, SQL mean across sensors, hourly roll-ups so history and seasonal comparison survive raw-data pruning (default raw 90 days, roll-ups 3 years), gate evaluation memoised, gzip and asset caching; measured with `scripts/benchmark.py`
- Tests: security, roles inventory, backup/restore, roll-ups and performance regression, smoke test of every GET endpoint
- Documentation: SECURITY, BACKUP_RESTORE, PERFORMANCE, TESTING, ESP32_SETUP (states that nodes are not implemented), BUDGET; INSTALLATION, SAFETY, ARCHITECTURE and README updated; all 17 requested files exist

**Not verified**
- No hardware of any kind has been driven by this code (RS485, I2C, 1-Wire, GPIO, relays, pumps, valves, motors); nothing has run on a Raspberry Pi; `install.sh`, the systemd unit, Dockerfile and docker-compose.yml are untested on a Pi/Docker
- No independent security review; HTTP is unencrypted unless you add a reverse proxy (untested example in SECURITY.md)
- Benchmark numbers come from a development PC; Pi numbers are unknown
- No automated UI tests; phone layout not checked

**Not implemented**: ESP32 nodes and MQTT, SCD41 driver, pulse flow meters, nutrient dosing/EC-pH control loops, PID control, heating-load calculation, per-value citations for crop data, Romanian translation of generated documents, second-factor authentication, automatic UPS shutdown, storage-wear monitoring, reports for periods older than raw retention

## Overall: what you can rely on and what you cannot

- Reliable by test: the logic (interlocks, rules, timing, calculations, access control, backup/restore, reports) against simulated and emulated hardware.
- Unproven: everything that touches the physical world. Treat the first commissioning as a supervised test, keep hardware protections independent, and use the commissioning checklist as the acceptance test.
- Guidance, not data: crop ranges, encyclopedia specifications, maintenance intervals, price estimates (only recorded offers are shown).

## Phase 7 - Hardware encyclopedia, setup wizard, installation manuals, maintenance, diagnostics

**Implemented and tested** (217 backend tests passing; frontend builds; a live server run returned wizard, manual (PDF), encyclopedia, health, explain and diagnose results and the four new pages rendered)
- Hardware encyclopedia: 25 categories (all of Part 10's list), 39 item pages, each with the required sections; compatibility checker per item and for custom devices; search; recorded offers shown as purchase info; "supported by this application" follows the real drivers. Specs only where established and labelled; no prices/URLs in static data (tested)
- Setup wizard: 11 state-driven steps (greenhouse inputs, planning/buying, Pi preparation, software, sensors, calibration, wiring, outputs, electrician sign-off, commissioning, automation, maintenance, manual) computed from the live system; hand-confirmed steps need a note
- Personalised manual generator: Markdown, HTML (offline, inline SVG diagram) and PDF (drawn diagram), plus a printable component-by-component checklist; content generated from the actual configuration (buses, addresses, GPIO, outputs, zones, windows, calibration, commissioning, maintenance); says so instead of printing generic wiring when no real hardware is registered; simulated devices are flagged
- Maintenance: schedule with due/overdue status and alerts, completion log, suggestions built from real equipment only (starting intervals, labelled), replacement history
- Diagnostics: system health with thresholds and alerts, communication statistics per sensor/bus, error log with explanations, plain-English explanation of 30+ real message types, live diagnosis assistant for sensors/outputs/zones/windows
- HARDWARE_GUIDE.md, MAINTENANCE.md, TROUBLESHOOTING.md

**Not verified**
- Encyclopedia texts and spec lines were written without per-statement citations; spec figures are limited to well-known datasheet values but have not been rechecked against datasheets here. Rules of thumb (replacement and maintenance intervals) are starting values, not manufacturer data
- Wizard steps and the manual's assembly order have not been followed on a real installation
- PDF/HTML manual layout was checked structurally and in tests, not visually on paper
- Nothing has run on a Raspberry Pi

**Not implemented / gaps**: SCD41 and ESP32 drivers (encyclopedia says so), storage-wear monitoring, UPS shutdown signalling, external notifications, per-output runtime hours, drag-based terminal-assignment documentation, translation of the manual to Romanian (language setting exists but only English text is generated), interactive wiring diagram, authentication

## Phase 6 - Greenhouse designer, plant profiles, VPD, DLI, analytics

**Implemented and tested** (151 backend tests passing; frontend builds; a live server run produced VPD/report/PDF output and the Map, Plants and Analytics pages rendered, including a drag in the designer)
- Plant knowledgebase: 8 built-in profiles with separate soil and hydroponic parameters, growth stages, pests, diseases, nutrients. All values labelled general guidance (not locally verified); water demand deliberately empty; user overrides marked, resettable; custom crops; validation of ranges
- Crop batches, harvest records, yield per m², live conditions check against the profile (no data never reads as OK)
- Analytics: VPD history with crop target band and in-band share, DLI per day from PAR history with coverage handling and target status, daily/weekly/monthly reports (JSON, CSV, PDF), seasonal comparison, raw CSV export, condensation indicator (labelled indicator only)
- Setpoint suggestions from a profile feeding the Phase 5 template (assumptions shown)
- Greenhouse map designer: drag and drop SVG editor, 17 item types, links to sensors/outputs/windows/zones/tanks, live readings, soil-moisture colouring, six toggleable layers + structure, grid snap, save/validate, PNG/SVG export (browser) and PDF export (server)
- KNOWLEDGEBASE_AND_ANALYTICS.md

**Not verified**
- Crop ranges are general guidance compiled without a local trial or source citations per value; they need review by a grower/agronomist before being relied on
- Report and chart accuracy on long real datasets (only synthetic data covers multi-day reports); PDF layout looked at only structurally
- Map PNG export and touch dragging were not exercised; drag was checked with synthesized mouse events
- Not run on a Raspberry Pi

**Not implemented / gaps**: per-value source citations in profiles, crop-stage-aware targets (one target set per crop), automatic application of crop targets to climate rules, energy metering beyond lighting, per-equipment runtime reports, pipe/cable routing as polylines (rectangles only), undo/redo in the map, map-driven irrigation/wiring design, authentication

## Phase 5 - Ventilation, heating, cooling, lighting, climate automation

**Implemented and tested** (127 backend tests passing; frontend builds; a live server run homed and positioned a simulated window, started heater + required fan, and cleared everything on e-stop)
- Climate engine with the same safety pattern as irrigation: interlocks before anything switches on, per-output runtime ceilings with blocked restart, outputs forced OFF at start-up/shutdown/e-stop
- Visual rule builder (API + UI): sensor, VPD, time-of-day, month and output-state conditions; match all/any; hysteresis; start/stop delays, min on/off, max on-time + cool-down; priorities (ties go to OFF); stale sensors never switch on; event record and notify
- Equipment interlocks per output: requires_on, forbids_on, min_on/off, stop_if safety sensor (mandatory for heaters and CO2), windows_max_open_pct
- Motorised windows/screens: two interlocked motor outputs, dead-reckoned position with limit-switch correction, homing from unknown position, overdrive at ends, rain/wind close with fail-safe on stale sensors, runtime-ceiling handling
- Lighting programs: photoperiod and DLI top-up with hysteresis, DLI and energy integration per day (persisted), history endpoint
- Setpoint template: generates day/night heating, vent and fan rules from user-entered setpoints only
- Commissioning extended to 14 checks; checks apply only to equipment that exists (heater/CO2 protection, window limits, pumps)
- Climate page (Basic: status, overrides, windows, lighting; Advanced: rule builder, template, setup), VENTILATION_GUIDE.md

**Not verified**
- No output driver has switched real hardware; window position accuracy and motor behaviour on real actuators are untested
- Not run on a Raspberry Pi
- Rule behaviour is verified with simulated sensors only; tuning of delays/hysteresis for a real greenhouse is the user's job

**Not implemented / gaps**: PID/proportional control, humidity template, heating-load calculation, solar-radiation shading logic, CO2 strategy beyond rules, wind/rain sensor drivers (use the generic Modbus or GPIO input drivers), UI editing of existing rules (create/enable/disable/delete only), authentication

## Phase 4 - Irrigation, pumps, valves, flow monitoring, water protection, safety interlocks

**Implemented and tested** (82 backend tests passing; frontend builds; a real server run switched valve then pump and integrated flow; UI rendered)
- Output drivers: simulated (with a simulated water plant), Raspberry Pi GPIO (gpiozero), Modbus coil relay (function 0x05); GPIO digital-input sensor driver (float switch)
- Pure interlock rules, unit-tested: tank/float/stale fail-safe, dead-head protection, flow low/high, feedback mismatch, runtime ceiling, idle leak
- Irrigation engine: valve -> settle -> pump sequencing, shared pumps, simultaneous-zone limit, minimum interval, hard per-output max runtime, outputs forced OFF at start/stop, persistent latched e-stop, failed ON aborts / failed OFF alerts and retries, measured water volume, run history, daily consumption
- Automatic irrigation (schedule + moisture trigger) gated by master switch, automation level, e-stop and the commissioning checklist; missed schedules skipped
- Commissioning: 12-check list with automatic logic tests and human-attested physical tests, bound to a hash of the equipment configuration; mixed simulated-interlock/real-output blocks the gate
- Irrigation page (Basic: water now, stop, e-stop, history; Advanced: outputs, commissioning, setup of outputs/tanks/zones/schedules), demo equipment in simulation mode
- IRRIGATION_GUIDE.md

**Not verified**
- No output driver (GPIO, Modbus coil) has switched real hardware; interlock timing with real pumps/valves is untested. Do the first commissioning supervised and rely on hardware protection.
- Not run on a Raspberry Pi
- The commissioning gate accepts attestations on trust; it cannot prove a physical test was done

**Not implemented / gaps**: pulse-counting flow meter driver, hydroponic nutrient dosing/EC-pH control, pressure-based pump protection, hardware watchdog automation (Phase 8), authentication (anyone on the network can press e-stop reset or water), frontend automated tests, UI for editing existing zones/outputs (create/delete only; PUT endpoints exist)

## Phase 3 - Hardware planner, shopping list, supplier research, budget, wiring, installation guides

**Implemented and tested** (53 backend tests passing; frontend builds; server started, pages rendered and Mermaid diagrams checked in the browser)
- Planner: Pi recommendation with reasoning; climate-station count (labelled heuristic); irrigation zones/drippers/flow/reservoir; ventilation from air volume x ACH (blocked until height, ACH and fan airflow are supplied); lighting from DLI/photoperiod/PPF (PPFD, not lux); 24 V supply sizing and DC fuse suggestions; DC cable voltage drop. Every number comes from user inputs or an editable, labelled assumption.
- Bill of materials (63 lines for the default 200 m² configuration) across all requested groups, with low/recommended/professional tiers and automatic adaptation to greenhouse size and growing method
- Offers: prices exist only when recorded as an offer (verified or your own estimate); VAT handling; budget by subsystem, tier totals, supplier comparison; purchased tick-boxes; CSV, Excel and PDF export
- Supplier research: one real product offer recorded (Raspberry Pi 5 4GB, Optimus Digital, 639 RON incl. taxes, read 2026-10-30) plus a directory of four suppliers with what was actually observed. The other named suppliers are marked unverified.
- Wiring designer: Mermaid system, power/protection and RS485 diagrams from the real registry; Modbus address table; Pi GPIO table with validated user assignments
- Docs: RASPBERRY_PI_SETUP, INSTALLATION, WIRING_GUIDE, SHOPPING_LIST, SAFETY

**Not verified**
- `deploy/install.sh` and `deploy/greenhouse.service` are syntax-checked only, never run on a Raspberry Pi
- Only one price has been verified; everything else is "requires verification". Product pages for DIN-rail supplies did not expose price/stock to the fetch tool, so no further offers were recorded.
- Pi setup commands (nmcli, raspi-config) are standard but not walked through on hardware
- No login/authentication: documented as a risk, to be built in Phase 8

**Not implemented / gaps**: named product recommendations for sensors, pumps, valves (the BOM lists generic requirements; Phase 7 encyclopedia adds product pages); terminal-assignment documentation; ESP32 setup guide; HARDWARE_GUIDE, IRRIGATION_GUIDE, VENTILATION_GUIDE, BUDGET.md; installation wizard and personalised manual generator (Phase 7); heating-load calculation; fan/vent opening-area geometry; interactive (drag) wiring diagram; the web bundle includes a large lazily-loaded Mermaid chunk.

## Phase 2 - Real sensor integrations, hardware registry, RS485/Modbus, calibration

**Implemented and tested against emulated hardware** (36 backend tests passing; frontend builds; server started and the new endpoints probed)
- Modbus RTU master (functions 3/4): CRC-16, framing, exception/CRC/timeout handling, int16/uint16/int32/uint32/float32 with word-order option, per-bus locking, automatic port reopen after I/O failure
- Generic Modbus sensor driver with user-supplied register definitions (no device maps shipped)
- DS18B20 (1-Wire via sysfs) and SHT3x (I2C, CRC-8) drivers
- Hardware registry API/UI: add/edit/delete sensors, driver-specific address validation, address-conflict detection, one-shot Test read, bus configuration, serial-port listing, read-only RS485 address scan (CRC errors flagged as possible address collision)
- Calibration: one-point, two-point, manual, reset; sane-gain check; append-only history; raw vs calibrated values shown
- Docs: MODBUS_SETUP.md, SENSOR_GUIDE.md, CALIBRATION_GUIDE.md

**Not verified**
- No driver has run against physical hardware (RS485 line, SHT3x, DS18B20); all flagged `hardware_tested: false`
- Not run on a Raspberry Pi; Windows serial open path only listed ports, not read from a device
- No frontend automated tests

**Not implemented**: SCD4x and other device drivers, ADC/GPIO inputs, MQTT/ESP32 nodes, calibration reminders (Phase 7), database migrations (a pre-Phase-2 database needs the new `sensors` columns; no such production database exists yet).

## Phase 1 - Architecture, database, Pi compatibility, dashboard, simulation, configuration

**Implemented and tested** (18 backend tests passing; frontend type-checks and builds; server started and probed over HTTP on Windows)
- Project structure and `docs/ARCHITECTURE.md`
- SQLite schema: settings, sensor registry, measurements, events, alerts; WAL mode, integrity check
- Greenhouse configuration model with owner defaults; unknown engineering inputs left `null` and reported
- Simulated driver + HAL interface; averaged/batched writes; retention pruning
- Sensor-fault and out-of-range handling with de-duplicated alerts that clear on recovery
- VPD and dew-point calculation (leaf = air temperature assumption stated), VPD history
- Raspberry Pi / host compatibility checks
- Commissioning gate (always closed)
- Dashboard (basic/advanced modes, light/dark), history chart, config editor, system page

**Not verified**
- Running on an actual Raspberry Pi (only Windows 11 / Python 3.13 so far)
- Frontend automated tests (none written; verified by type-check, build and a manual screenshot)

**Not started** (Phases 7-8): wizard, hardware encyclopedia, manual generator, maintenance, security hardening, backup/restore, systemd/Docker, and the remaining documentation files (INSTALLATION, HARDWARE_GUIDE, WIRING_GUIDE, etc.).
