# ESP32 remote nodes

**Status: NOT IMPLEMENTED.** This application has no ESP32 firmware, no MQTT broker integration and no node driver. Nothing in this document describes a working feature. It exists so the planned architecture is written down and so you do not build hardware around something that is not there.

## What works today instead

Distributed sensing works over **RS485/Modbus** (long cables, many devices): see MODBUS_SETUP.md and SENSOR_GUIDE.md. Outputs can be switched by Modbus relay boards (`modbus_coil` driver), Raspberry Pi GPIO through isolated drivers, or simulated outputs. Both are tested only against emulation (STATUS.md).

## Planned design (not built)

- Raspberry Pi stays the single controller and decision maker; an ESP32 is a dumb I/O node that publishes readings and accepts output commands over MQTT.
- An MQTT broker (for example Mosquitto) would run on the Pi, bound to the local network, with authentication and, ideally, TLS.
- A `mqtt_node` sensor driver and output driver would map MQTT topics to registry entries, with freshness checks identical to today's sensors: a silent node means "stale" and every interlock treats stale as unsafe.
- Node outputs would need a node-side watchdog that switches outputs OFF when the controller stops talking, because a Wi-Fi link can fail while the node stays powered.
- Commissioning would need new checks (node link loss turns outputs off).

## If you want ESP32 hardware anyway

Treat it as your own project outside this application. Rules that would still apply: 3.3 V logic only; do not use the on-chip ADC for measurements that matter (use an external ADC); never connect mains to an ESP32 board; keep hardware protections independent of the node; use a regulated supply. See the Encyclopedia pages "ESP32 development board" and the compatibility checker.

## Not documented because it does not exist

Flashing instructions, topic names, payload formats, pin assignments for specific boards, OTA updates. None of these are specified or tested.
