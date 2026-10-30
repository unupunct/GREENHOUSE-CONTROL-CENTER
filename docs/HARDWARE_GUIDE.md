# Hardware guide

The **Encyclopedia** page is the hardware guide: 25 categories (Raspberry Pi, ESP32, temperature, humidity, soil moisture, CO₂, light, PAR, pH, EC, water level, flow, pumps, valves, fans, linear actuators, relays, MOSFET drivers, power supplies, UPS, RS485 adapters, enclosures, connectors, cables, safety) with 39 item pages. Every page has: what it does, how it works, why it is needed, wiring, installation, configuration, calibration, troubleshooting, maintenance, replacement guidance, recommended models, alternatives, specifications (only where established), compatibility, and purchase information.

## How to read it

- **Specifications** appear only for parts whose datasheet values are well established (Raspberry Pi 4/5 basics, ESP32 basics, DS18B20, SHT3x, SCD41) and are labelled *verify against the datasheet of the exact part you buy*. For generic categories (industrial RS485 probes, pumps, valves, fans...) no figures are given because they depend on the exact product.
- **Recommended models** are named only where the product family is well known. Generic entries say what to look for. No register maps are shipped.
- **Replacement intervals** are rules of thumb, marked as such, unless stated otherwise.
- **Prices and links** appear only for items with a recorded supplier offer (Shopping page). Everything else says "No price recorded"; nothing is estimated.
- **Supported by this application** shows whether a driver exists and that **no driver has been tested on physical hardware yet**.

## Compatibility checker

Per item (and for any device you describe) it answers: can it connect to the Raspberry Pi directly or with an adapter, which protocol, does it need an ADC (the Pi has none), does it need external power, can it be used with an ESP32 (ESP32 nodes are not implemented in this application yet), and what to watch out for (3.3 V logic, mains, short I2C cables, 1-Wire pull-up, level shifting for pulses).

Rules used: I2C/1-Wire/SPI/UART/GPIO connect directly; RS485 needs a USB-RS485 adapter; analogue voltages need an external ADC; 4-20 mA needs an isolated receiver or an RS485 variant; pulse outputs need level shifting or isolation; mains and DC power items have no data connection and are switched through a driver, relay or contactor.

Related guides: SENSOR_GUIDE.md, MODBUS_SETUP.md, WIRING_GUIDE.md, SAFETY.md.
