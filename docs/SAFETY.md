# Safety

1. **Mains installation by a qualified electrician.** This project documents mains at a conceptual level only. It calculates no breaker, RCD or mains cable sizes.
2. **Protective devices are independent of the software.** Float switch (pump dry-run), heater over-temperature cut-out, motor limit switches, e-stop, fuses/breakers, RCD and surge protection must work with the Raspberry Pi switched off or crashed.
3. **No automatic operation until commissioning passes.** The gate (`GET /api/safety`) needs all 12 checks; physical checks need a person to perform and attest them (IRRIGATION_GUIDE.md). Manual control still obeys interlocks and runtime limits.
4. **GPIO is 3.3 V logic.** Drive isolated modules, never mains devices directly.
5. **Calculated values are estimates.** Fuse suggestions, voltage drop and supply sizes are conceptual starting points to hand to a qualified person.
6. **Access control.** Sign-in and roles protect the web interface (SECURITY.md), but the connection is plain HTTP unless you add TLS: keep it on a trusted network. This does not replace physical access control to the greenhouse and cabinet.

7. **Software interlocks are a second line of defence** (tank level, dead-head, flow, runtime, e-stop latch). They are not hardware-tested yet and do not replace hardware protection.
8. **Roles.** Any signed-in user can press the software e-stop; resetting it and starting watering need the operator role; configuration and commissioning attestations need an administrator.

9. **Heaters and CO2:** every heater needs an independent hardware over-temperature cut-out; every CO2 supply an independent shut-off and a room CO2 alarm. The software `stop_if` limit is mandatory but is only a second line of defence. CO2 enrichment can harm people.
10. **Windows:** fit end-of-travel limit switches or motor protection; open/close are interlocked in software but must also never be energised together by the wiring.
