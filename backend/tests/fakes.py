"""Emulated buses used instead of hardware."""

from __future__ import annotations

import struct

from app.hal.drivers import crc8_sensirion
from app.hal.i2c import I2CManager
from app.hal.modbus_rtu import BusConfig, BusManager, ModbusTimeout, crc16, with_crc


class FakeModbusTransport:
    """Behaves like an RS485 line with a few slave devices.

    slaves: {slave_id: {(function, register): int_value_of_one_register}}
    """

    def __init__(self, cfg: BusConfig, slaves: dict, silent=(), corrupt=()):
        self.cfg, self.slaves = cfg, slaves
        self.silent, self.corrupt = set(silent), set(corrupt)
        self._buf = b""
        self.requests: list[bytes] = []
        self.coils: dict[tuple[int, int], bool] = {}
        self.closed = False

    def reset_input(self):
        self._buf = b""

    def write(self, data: bytes):
        self.requests.append(data)
        assert struct.unpack("<H", data[-2:])[0] == crc16(data[:-2]), "master sent a bad CRC"
        slave, func, reg, count = struct.unpack(">BBHH", data[:-2])
        if slave in self.silent or slave not in self.slaves:
            return
        if func == 5:  # write single coil: record and echo
            self.coils[(slave, reg)] = count == 0xFF00
            self._buf = data
            return
        regs = self.slaves[slave]
        words = [regs.get((func, reg + i)) for i in range(count)]
        if any(w is None for w in words):
            frame = with_crc(bytes([slave, func | 0x80, 2]))  # illegal data address
        else:
            payload = b"".join(struct.pack(">H", w & 0xFFFF) for w in words)
            frame = with_crc(bytes([slave, func, len(payload)]) + payload)
        if slave in self.corrupt:
            frame = frame[:-1] + bytes([frame[-1] ^ 0xFF])
        self._buf = frame

    def read_exact(self, n: int, timeout: float) -> bytes:
        if len(self._buf) < n:
            self._buf = b""
            raise ModbusTimeout("fake timeout")
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def close(self):
        self.closed = True


def make_bus_manager(slaves, **kw) -> tuple[BusManager, list[FakeModbusTransport]]:
    made: list[FakeModbusTransport] = []

    def factory(cfg):
        t = FakeModbusTransport(cfg, slaves, **kw)
        made.append(t)
        return t

    return BusManager(factory), made


class FakeSht3x:
    def __init__(self, temp_c=21.5, rh=55.0, corrupt=False):
        self.temp_c, self.rh, self.corrupt = temp_c, rh, corrupt
        self.calls = 0

    def transfer(self, addr, write, read_len, delay_s):
        assert addr in (0x44, 0x45) and write == b"\x24\x00" and read_len == 6
        self.calls += 1
        t = round((self.temp_c + 45) / 175 * 65535)
        h = round(self.rh / 100 * 65535)
        tb, hb = struct.pack(">H", t), struct.pack(">H", h)
        crc_t = crc8_sensirion(tb) ^ (0xFF if self.corrupt else 0)
        return tb + bytes([crc_t]) + hb + bytes([crc8_sensirion(hb)])


def make_i2c_manager(device) -> I2CManager:
    return I2CManager(lambda number: device)
