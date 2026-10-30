# Wiring guide

The **Wiring** page (Advanced mode) generates diagrams from your actual configuration: system architecture, power distribution with protection, and the RS485 bus (from registered Modbus sensors and configured buses). They are **conceptual**: they show what connects to what, not the terminals of any specific product. Pin-level wiring comes from each device's datasheet; the application does not guess it.

## Four separate domains

1. **Low-voltage electronics** - Raspberry Pi, sensors, logic.
2. **DC actuator power** - 24 V supply, fuses per feeder, DC MOSFET drivers/relays, valves, vent actuators.
3. **Mains distribution** - breakers, RCD, surge protection, contactors, fans/heaters/lights. **Qualified electrician only.**
4. **Safety/protection** - e-stop, float switch in the pump circuit, heater over-temperature cut-out, motor limit switches. Independent of the software.

**Never connect mains voltage to Raspberry Pi GPIO or to hobby relay boards.** GPIO pins are 3.3 V logic and must drive isolated driver modules only.

## GPIO table

Fixed entries are only the Pi interfaces this application uses: I2C1 (SDA GPIO2 / pin 3, SCL GPIO3 / pin 5) and the default 1-Wire pin (GPIO4 / pin 7). Other assignments are yours: the page validates (BCM 2-27, no duplicates, no use of pins reserved for I2C/1-Wire) but suggests none for specific devices.

## Cable planning

The Planner has a DC voltage-drop calculator (copper, two conductors: drop = 2·L·I·ρ/A). It does **not** check current rating, insulation, installation method or protection; the electrician must.

## RS485

Daisy-chain, A/B twisted pair, termination only at the two ends, one bias point, unique addresses, shield earthed at one end. See MODBUS_SETUP.md.
