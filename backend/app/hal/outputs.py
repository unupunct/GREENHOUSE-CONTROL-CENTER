"""Output (actuator) drivers: pumps, valves, relays.

All drivers are unverified on hardware (``hardware_tested`` False). Drivers only
switch; every safety decision is made by app.automation, and hardware
protections must exist independently of this code.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from app.hal.base import DriverError
from app.hal.context import HalContext
from app.hal.modbus_rtu import ModbusError


@dataclass(frozen=True)
class OutputSpec:
    id: str
    kind: str
    address: dict = field(default_factory=dict)


class SimulatedOutput:
    name = "simulated_output"
    label = "Simulated output (demo)"
    protocol = "none"
    hardware_tested = False
    address_help = "Optional sim_flow_lpm (pumps): flow produced by the simulated plant."

    def __init__(self, ctx: HalContext) -> None:
        self.ctx = ctx

    def validate_address(self, address: dict, kind: str) -> dict:
        return dict(address)

    def conflict_key(self, address: dict, kind: str):
        return None

    async def set(self, spec: OutputSpec, on: bool) -> None:
        self.ctx.plant.register(spec.id, spec.kind, float(spec.address.get("sim_flow_lpm", 0.0)))
        self.ctx.plant.set(spec.id, on)


class _GpioAddr(BaseModel):
    pin: int = Field(ge=4, le=27, description="BCM number; 2 and 3 are reserved for I2C")
    active_high: bool = True


class GpioOutput:
    name = "gpio_output"
    label = "Raspberry Pi GPIO output (via isolated driver module)"
    protocol = "GPIO"
    hardware_tested = False
    address_help = ("pin (BCM 4-27), active_high. GPIO is 3.3 V logic: drive an isolated MOSFET/relay "
                    "module, never a mains device directly. Uses gpiozero.")

    def __init__(self, ctx: HalContext) -> None:
        self.ctx = ctx
        self._dev: dict[int, object] = {}

    def validate_address(self, address: dict, kind: str) -> dict:
        return _GpioAddr.model_validate(address).model_dump()

    def conflict_key(self, address: dict, kind: str):
        return (_GpioAddr.model_validate(address).pin,)

    def _set_sync(self, a: _GpioAddr, on: bool) -> None:
        try:
            if a.pin not in self._dev:
                from gpiozero import OutputDevice  # lazy: Pi only
                self._dev[a.pin] = OutputDevice(a.pin, active_high=a.active_high, initial_value=False)
            dev = self._dev[a.pin]
            dev.on() if on else dev.off()  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            raise DriverError(f"GPIO {a.pin}: {exc}") from exc

    async def set(self, spec: OutputSpec, on: bool) -> None:
        await asyncio.to_thread(self._set_sync, _GpioAddr.model_validate(spec.address), on)


class _CoilAddr(BaseModel):
    bus: str
    slave: int = Field(ge=1, le=247)
    coil: int = Field(ge=0, le=65535)
    active_high: bool = True


class ModbusCoilOutput:
    name = "modbus_coil"
    label = "Modbus RTU relay/coil (RS485)"
    protocol = "RS485"
    hardware_tested = False
    address_help = ("bus, slave, coil (0-based protocol address from the device datasheet), active_high. "
                    "Uses function 0x05 (write single coil).")

    def __init__(self, ctx: HalContext) -> None:
        self.ctx = ctx

    def validate_address(self, address: dict, kind: str) -> dict:
        return _CoilAddr.model_validate(address).model_dump()

    def conflict_key(self, address: dict, kind: str):
        a = _CoilAddr.model_validate(address)
        return (a.bus, a.slave, a.coil)

    def _set_sync(self, a: _CoilAddr, on: bool) -> None:
        bus = self.ctx.buses.get(a.bus)
        try:
            bus.write_single_coil(a.slave, a.coil, on if a.active_high else not on)
        except ModbusError:
            raise
        except Exception as exc:  # noqa: BLE001
            self.ctx.buses.drop(a.bus)
            raise DriverError(f"serial error on bus '{a.bus}': {exc}") from exc

    async def set(self, spec: OutputSpec, on: bool) -> None:
        await asyncio.to_thread(self._set_sync, _CoilAddr.model_validate(spec.address), on)


OUTPUT_DRIVERS: dict[str, type] = {c.name: c for c in (SimulatedOutput, GpioOutput, ModbusCoilOutput)}
IRRIGATION_KINDS = ("pump", "valve", "dosing")
CLIMATE_KINDS = ("fan", "heater", "cooler", "humidifier", "dehumidifier", "light", "co2", "motor", "other")
OutputKind = Literal["pump", "valve", "dosing", "fan", "heater", "cooler", "humidifier", "dehumidifier",
                     "light", "co2", "motor", "other"]


class OutputRegistry:
    def __init__(self, ctx: HalContext) -> None:
        self.ctx = ctx
        self._inst: dict[str, object] = {}

    def get(self, name: str):
        if name not in self._inst:
            try:
                self._inst[name] = OUTPUT_DRIVERS[name](self.ctx)
            except KeyError:
                raise DriverError(f"no output driver '{name}'") from None
        return self._inst[name]

    def describe(self) -> list[dict]:
        return [{"name": n, "label": c.label, "protocol": c.protocol, "hardware_tested": c.hardware_tested,
                 "address_help": c.address_help} for n, c in OUTPUT_DRIVERS.items()]
