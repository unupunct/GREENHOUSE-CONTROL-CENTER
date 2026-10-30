"""Real sensor drivers.

``hardware_tested`` is False for all of them: they are implemented from public
datasheets/specifications and verified against emulated buses in the test
suite, NOT against physical devices. Flip the flag only after testing on real
hardware.
"""

from __future__ import annotations

import asyncio
import re
import time

from pydantic import BaseModel, Field

from app.hal.base import DriverError, SensorSpec
from app.hal.context import HalContext
from app.hal.modbus_rtu import DATATYPES, ModbusAddress, ModbusError, decode_value


class ModbusRtuDriver:
    name = "modbus_rtu"
    label = "Modbus RTU register (RS485)"
    protocol = "RS485"
    kinds = None
    hardware_tested = False
    address_help = ("bus, slave (1-247), function (3 holding / 4 input), register (0-based protocol "
                    "address), datatype, word_order, scale/offset. Take the register map from the "
                    "device's own datasheet - this application ships none.")

    def __init__(self, ctx: HalContext) -> None:
        self.ctx = ctx

    def validate_address(self, address: dict, kind: str) -> dict:
        return ModbusAddress.model_validate(address).model_dump()

    def conflict_key(self, address: dict, kind: str):
        a = ModbusAddress.model_validate(address)
        return (a.bus, a.slave, a.function, a.register)

    def _read_sync(self, a: ModbusAddress) -> float:
        bus = self.ctx.buses.get(a.bus)
        try:
            data = bus.read_registers(a.slave, a.function, a.register, DATATYPES[a.datatype])
        except ModbusError:
            raise
        except Exception as exc:  # serial I/O failure: reopen the port next time
            self.ctx.buses.drop(a.bus)
            raise DriverError(f"serial error on bus '{a.bus}': {exc}") from exc
        return decode_value(data, a.datatype, a.word_order) * a.scale + a.offset

    async def read(self, spec: SensorSpec, now: float) -> float:
        a = ModbusAddress.model_validate(spec.address)
        return round(await asyncio.to_thread(self._read_sync, a), 4)


class _W1Address(BaseModel):
    device_id: str = Field(pattern=r"^28-[0-9a-f]{12}$")  # 28 = DS18B20 family code


class Ds18b20Driver:
    name = "ds18b20"
    label = "DS18B20 temperature probe (1-Wire)"
    protocol = "1-Wire"
    kinds = ("temperature",)
    hardware_tested = False
    address_help = ("device_id like 28-0123456789ab (listed under /sys/bus/w1/devices once the "
                    "w1-gpio overlay is enabled).")

    def __init__(self, ctx: HalContext) -> None:
        self.ctx = ctx

    def validate_address(self, address: dict, kind: str) -> dict:
        return _W1Address.model_validate(address).model_dump()

    def conflict_key(self, address: dict, kind: str):
        return (_W1Address.model_validate(address).device_id,)

    def _read_sync(self, device_id: str) -> float:
        path = self.ctx.w1_dir / device_id / "w1_slave"
        try:
            lines = path.read_text().strip().splitlines()
        except OSError as exc:
            raise DriverError(f"cannot read {path}: {exc}") from exc
        if len(lines) < 2 or not lines[0].rstrip().endswith("YES"):
            raise DriverError("DS18B20 CRC check failed (wiring, pull-up or cable length?)")
        m = re.search(r"t=(-?\d+)", lines[1])
        if not m:
            raise DriverError("unparseable DS18B20 output")
        milli = int(m.group(1))
        if milli == 85000:  # power-on reset value of the DS18B20: conversion didn't run
            raise DriverError("DS18B20 returned 85.0 C (power-on value): check supply/pull-up")
        return milli / 1000.0

    async def read(self, spec: SensorSpec, now: float) -> float:
        return await asyncio.to_thread(self._read_sync, _W1Address.model_validate(spec.address).device_id)

    def list_devices(self) -> list[str]:
        try:
            return sorted(p.name for p in self.ctx.w1_dir.iterdir() if p.name.startswith("28-"))
        except OSError:
            return []


def crc8_sensirion(data: bytes) -> int:
    """CRC-8, polynomial 0x31, init 0xFF (Sensirion devices)."""
    crc = 0xFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x31) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


class _Sht3xAddress(BaseModel):
    bus: int = Field(1, ge=0, le=20)  # Linux I2C bus number (Pi default: 1)
    i2c_address: int = Field(0x44, description="0x44 (ADDR low) or 0x45 (ADDR high)")


class Sht3xDriver:
    name = "sht3x"
    label = "Sensirion SHT3x temperature/humidity (I2C)"
    protocol = "I2C"
    kinds = ("temperature", "humidity")
    hardware_tested = False
    address_help = "bus (Pi: 1), i2c_address 68 (0x44) or 69 (0x45). One row per quantity (temperature, humidity)."

    CMD_SINGLE_SHOT_HIGH = b"\x24\x00"  # clock stretching disabled, high repeatability
    MEASURE_DELAY_S = 0.016  # datasheet max 15 ms for high repeatability

    def __init__(self, ctx: HalContext) -> None:
        self.ctx = ctx
        self._cache: dict[tuple[int, int], tuple[float, float, float]] = {}

    def validate_address(self, address: dict, kind: str) -> dict:
        a = _Sht3xAddress.model_validate(address)
        if a.i2c_address not in (0x44, 0x45):
            raise ValueError("SHT3x address must be 0x44 (68) or 0x45 (69)")
        return a.model_dump()

    def conflict_key(self, address: dict, kind: str):
        a = _Sht3xAddress.model_validate(address)
        return (a.bus, a.i2c_address, kind)

    def _measure_sync(self, bus: int, addr: int) -> tuple[float, float]:
        key = (bus, addr)
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[2] < 1.0:  # temp+RH rows share one measurement
            return hit[0], hit[1]
        raw = self.ctx.i2c.get(bus).transfer(addr, self.CMD_SINGLE_SHOT_HIGH, 6, self.MEASURE_DELAY_S)
        if len(raw) != 6:
            raise DriverError(f"SHT3x short read ({len(raw)} bytes)")
        if crc8_sensirion(raw[0:2]) != raw[2] or crc8_sensirion(raw[3:5]) != raw[5]:
            raise DriverError("SHT3x CRC error (wiring/pull-ups/cable length?)")
        t = -45.0 + 175.0 * ((raw[0] << 8) | raw[1]) / 65535.0
        rh = 100.0 * ((raw[3] << 8) | raw[4]) / 65535.0
        self._cache[key] = (t, rh, time.monotonic())
        return t, rh

    async def read(self, spec: SensorSpec, now: float) -> float:
        a = _Sht3xAddress.model_validate(spec.address)
        t, rh = await asyncio.to_thread(self._measure_sync, a.bus, a.i2c_address)
        return round(t if spec.kind == "temperature" else rh, 3)


class _GpioInAddr(BaseModel):
    pin: int = Field(ge=4, le=27)
    pull_up: bool = True
    invert: bool = False  # value 1 = "OK / water present" after inversion


class GpioInputDriver:
    """Digital input (float switch, limit switch, e-stop monitor). Value 1.0/0.0."""

    name = "gpio_input"
    label = "Raspberry Pi GPIO digital input (float switch etc.)"
    protocol = "GPIO"
    kinds = ("float_switch", "other")
    hardware_tested = False
    address_help = ("pin (BCM 4-27), pull_up, invert. The raw pin level is 1 when high; use invert so "
                    "that 1 always means 'OK' (e.g. water present). Uses gpiozero.")

    def __init__(self, ctx: HalContext) -> None:
        self.ctx = ctx
        self._dev: dict[int, object] = {}

    def validate_address(self, address: dict, kind: str) -> dict:
        return _GpioInAddr.model_validate(address).model_dump()

    def conflict_key(self, address: dict, kind: str):
        return (_GpioInAddr.model_validate(address).pin,)

    def _read_sync(self, a: _GpioInAddr) -> float:
        try:
            if a.pin not in self._dev:
                from gpiozero import DigitalInputDevice  # lazy: Pi only
                self._dev[a.pin] = DigitalInputDevice(a.pin, pull_up=a.pull_up)
            raw = bool(self._dev[a.pin].value)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            raise DriverError(f"GPIO {a.pin}: {exc}") from exc
        return 1.0 if raw != a.invert else 0.0

    async def read(self, spec: SensorSpec, now: float) -> float:
        return await asyncio.to_thread(self._read_sync, _GpioInAddr.model_validate(spec.address))
