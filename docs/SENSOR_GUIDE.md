# Sensor guide

All drivers below are written from public datasheets/specifications and tested against **emulated** buses/files. None has been verified on physical hardware yet (`hardware_tested: false` in `GET /api/hardware/drivers`). Test each sensor with the **Test** button and compare with a reference instrument before relying on it.

Product choices, prices and accuracy figures belong to the Planner and Shopping pages; this guide intentionally contains none.

## DS18B20 (1-Wire) - driver `ds18b20`

Kinds: temperature. Good for water/nutrient solution and for cable runs longer than I2C allows.

Wiring (Raspberry Pi): VDD to 3.3 V, GND to GND, DATA to GPIO4 (physical pin 7), **4.7 kΩ resistor between DATA and 3.3 V**. Waterproof probes are available; check the probe's wire colours on its datasheet.

Enable 1-Wire: add `dtoverlay=w1-gpio` to `/boot/firmware/config.txt` (older images: `/boot/config.txt`) and reboot, or use `sudo raspi-config` → Interface Options → 1-Wire. Probes then appear as `/sys/bus/w1/devices/28-xxxxxxxxxxxx`.

Register: Hardware → Add sensor → driver DS18B20, address `{"device_id": "28-xxxxxxxxxxxx"}`. Errors reported in plain terms: CRC failure (wiring/pull-up/cable) and the 85.0 °C power-on value (conversion did not run).

## SHT3x temperature/humidity (I2C) - driver `sht3x`

Kinds: temperature, humidity - **add one row per quantity**; both share a single measurement per second.

Wiring (Raspberry Pi): VIN to 3.3 V (pin 1), GND (pin 6), SDA to GPIO2 (pin 3), SCL to GPIO3 (pin 5). Breakout boards generally carry pull-ups; the Pi also has them on these pins. Keep I2C cables short (roughly tens of centimetres); for distant positions use an RS485 sensor or a remote node instead.

Enable I2C: `sudo raspi-config nonint do_i2c 0`, reboot, then check `sudo apt install -y i2c-tools && i2cdetect -y 1`. The chip appears at 0x44 or 0x45 depending on its ADDR pin.

Register: address `{"bus": 1, "i2c_address": 68}` (68 = 0x44, 69 = 0x45). Single-shot, high-repeatability mode with CRC check.

## Generic Modbus RTU register - driver `modbus_rtu`

For any RS485/Modbus sensor (soil probes, pH/EC transmitters, CO₂, PAR...). You supply the register definition from the datasheet. See MODBUS_SETUP.md.

## Simulated - driver `simulated`

Demo data only; always flagged "simulated". Delete the demo sensors (Hardware → Delete) as real ones replace them, or start with `GCC_SIMULATE=false` on a fresh database to skip the demo set.

## Not yet implemented

SCD4x CO₂ (I2C), ADC-based analogue sensors, GPIO inputs (flow meter pulses, float switches), MQTT/ESP32 nodes, and any device-specific profiles.
