# Calibration guide

The application applies a linear correction per sensor:

    calibrated = gain × raw + offset

`raw` is the driver's value after the datasheet scaling (Modbus `scale`/`offset`). Every calibration is stored in an append-only history with a note. Only the calibrated value is stored in the measurement history, so a calibration change affects new samples only. The live raw value is shown in the Hardware page.

Calibration needs a **trustworthy reference**: a better instrument at the same spot, or a known solution (pH buffers, EC standard). Without one, leave sensors uncalibrated; guessing adds error.

## Methods (Hardware → Calibrate)

- **One-point (offset):** let the sensor and reference settle in the same conditions, enter the reference value; the offset is computed from the live raw reading, keeping the existing gain. Right for temperature probes that read a constant amount high/low.
- **Two-point:** take two readings far apart in the range (e.g. pH 7.00 and 4.01 buffers; ice bath and warm water). Enter the raw and reference values for both. The gain must be positive and between 0.1 and 10, otherwise the entry is rejected as a likely mistake.
- **Reset:** back to gain 1, offset 0.

## Practical notes

- Allow sensors time to stabilise; probes need time in the solution/bath.
- Soil moisture readings depend on soil type and probe contact; a calibration against known wet/dry samples applies to *that* soil. Treat inexpensive probes as indicators, not laboratory instruments.
- pH and EC probes drift and need frequent re-calibration; create calibration reminders on the Maintenance page ("Create from my equipment") and note the date in the calibration note field.
