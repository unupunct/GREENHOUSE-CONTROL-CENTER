# Modbus RTU / RS485 setup

Implemented in `backend/app/hal/modbus_rtu.py`. Read-only master: function 3 (holding registers) and 4 (input registers). Framing, CRC and decoding are unit-tested against an emulated bus; **not yet tested on a physical RS485 line**.

The application ships **no register maps**. Take slave address, function, register, data type, scaling and word order from your device's datasheet.

## Wiring principles (RS485)

- **Two wires, A and B (also labelled D-/D+ or –/+; labelling is not consistent between vendors).** If a device never answers and everything else is right, swapping A/B is a legitimate fix.
- **Daisy-chain (line) topology only.** One cable runs past each device. Avoid stars; keep stubs as short as possible.
- **Termination:** a 120 Ω resistor across A-B at **each of the two physical ends** of the line, and nowhere else. Many adapters/devices have a switchable one.
- **Biasing:** when nobody is transmitting, the pair must idle in a defined state (one wire pulled up, the other pulled down) or receivers may see noise as data. Bias is applied at **one** point on the bus, usually the master end, and many USB-RS485 adapters already include it. Which wire is pulled which way depends on the A/B labelling of your adapter, so follow its documentation rather than adding resistors blindly.
- **Reference/ground:** use a shielded twisted pair for A/B. Connect the shield to earth at one end only. If devices are powered from different supplies, a third "common/GND" conductor is often recommended by device makers; follow the device datasheet.
- **Unique slave addresses** (1-247) per bus. Two devices with the same address answer simultaneously and corrupt each other's replies.

## Configure in the application

1. Plug in the USB-RS485 adapter. On Linux add your user to the serial group once: `sudo usermod -aG dialout $USER`, then log out and in.
2. Advanced mode → **Hardware** → add a bus: ID (e.g. `rs485_1`), port (`/dev/ttyUSB0`, or `COM3` on Windows), baud rate, parity, stop bits - **these must match the devices**. Save.
3. **Scan** a small address range using a register that exists on your device (a miss costs one timeout each; max 32 addresses per scan).
4. **Add sensor** with driver "Modbus RTU register", e.g.:

```json
{"bus": "rs485_1", "slave": 3, "function": 3, "register": 0,
 "datatype": "int16", "word_order": "big", "scale": 0.1, "offset": 0}
```

`value = raw * scale + offset` (device scaling from the datasheet). Use **Test** to do one live read; fix problems before relying on it. Calibration (user correction against a reference) is separate: see CALIBRATION_GUIDE.md.

**Register numbering:** `register` is the 0-based protocol address. Datasheets that list `40001` mean protocol address 0 (holding) and `30001` means 0 (input).

## Troubleshooting

| Message | Likely cause |
|---|---|
| `no/partial response` (timeout) | wrong slave address, baud/parity mismatch, A/B swapped, device unpowered, missing termination on a long line |
| `CRC mismatch` | noise, wrong baud/parity, **two devices with the same address**, no/extra termination |
| `Modbus exception 2 (illegal data address)` | the device is there, but that register doesn't exist - check register numbering (0 vs 1 based) |
| `Modbus exception 1` | wrong function code (try 3 vs 4) |
| `cannot open <port>` | adapter not plugged in, wrong port name, no permission (dialout group) |
| value is huge/tiny/odd | wrong datatype, word order, or scale |

A failing sensor raises one alert (and logs one event); it clears automatically when reads succeed again. Polling is sequential, so many unresponsive devices slow each poll cycle by `timeout_s` each; keep timeouts modest and fix dead devices.
