"""Minimal I2C transfer abstraction (smbus2 on Linux, fakes in tests)."""

from __future__ import annotations

import time
from typing import Protocol

from app.hal.base import DriverError


class I2CBus(Protocol):
    def transfer(self, addr: int, write: bytes, read_len: int, delay_s: float) -> bytes:
        """Write ``write``, wait ``delay_s``, then read ``read_len`` bytes."""
        ...


class SmbusI2C:
    def __init__(self, bus_number: int) -> None:
        from smbus2 import SMBus  # lazy; Linux only

        self._bus = SMBus(bus_number)

    def transfer(self, addr: int, write: bytes, read_len: int, delay_s: float) -> bytes:
        from smbus2 import i2c_msg

        try:
            if write:
                self._bus.i2c_rdwr(i2c_msg.write(addr, list(write)))
            if delay_s:
                time.sleep(delay_s)
            if read_len:
                msg = i2c_msg.read(addr, read_len)
                self._bus.i2c_rdwr(msg)
                return bytes(msg)
            return b""
        except OSError as exc:
            raise DriverError(f"I2C error at 0x{addr:02x}: {exc}") from exc


class I2CManager:
    def __init__(self, factory=None) -> None:
        self._factory = factory or SmbusI2C
        self._buses: dict[int, I2CBus] = {}

    def get(self, number: int) -> I2CBus:
        if number not in self._buses:
            try:
                self._buses[number] = self._factory(number)
            except Exception as exc:  # noqa: BLE001  (no smbus2 / no /dev/i2c-N)
                raise DriverError(f"cannot open I2C bus {number}: {exc} "
                                  "(is I2C enabled and smbus2 installed?)") from exc
        return self._buses[number]
