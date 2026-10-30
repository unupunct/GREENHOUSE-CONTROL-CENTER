"""Modbus RTU master (read-only: function codes 0x03 and 0x04).

Implemented from the public Modbus serial-line specification. The framing code
is pure and unit-tested; the serial transport is only exercised against real
hardware by the user (see docs/STATUS.md).

Register addresses here are PROTOCOL addresses (0-based). Many datasheets list
"40001"-style 1-based addresses; subtract the 40001/30001 offset yourself.
"""

from __future__ import annotations

import struct
import threading
import time
from typing import Literal, Protocol

from pydantic import BaseModel, Field, model_validator

from app.hal.base import DriverError


class ModbusError(DriverError):
    pass


class ModbusTimeout(ModbusError):
    pass


class ModbusCrcError(ModbusError):
    pass


class ModbusException(ModbusError):
    EXCEPTIONS = {1: "illegal function", 2: "illegal data address", 3: "illegal data value",
                  4: "slave device failure", 6: "slave busy"}

    def __init__(self, code: int) -> None:
        self.code = code
        super().__init__(f"device returned Modbus exception {code} "
                         f"({self.EXCEPTIONS.get(code, 'unknown')})")


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def with_crc(frame: bytes) -> bytes:
    return frame + struct.pack("<H", crc16(frame))  # CRC is sent low byte first


def build_read_request(slave: int, function: int, register: int, count: int) -> bytes:
    return with_crc(struct.pack(">BBHH", slave, function, register, count))


DATATYPES = {"uint16": 1, "int16": 1, "uint32": 2, "int32": 2, "float32": 2}


def decode_value(data: bytes, datatype: str, word_order: str = "big") -> float:
    """Decode register bytes. 32-bit values span two registers; ``word_order``
    'big' means the high word comes first (the Modbus convention is NOT
    uniform across vendors, so this is configurable)."""
    if DATATYPES[datatype] == 2 and word_order == "little":
        data = data[2:4] + data[0:2]
    fmt = {"uint16": ">H", "int16": ">h", "uint32": ">I", "int32": ">i", "float32": ">f"}[datatype]
    return struct.unpack(fmt, data)[0]


class Transport(Protocol):
    def reset_input(self) -> None: ...
    def write(self, data: bytes) -> None: ...
    def read_exact(self, n: int, timeout: float) -> bytes:
        """Return exactly ``n`` bytes or raise :class:`ModbusTimeout`."""
        ...
    def close(self) -> None: ...


class BusConfig(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]{1,32}$")
    type: Literal["modbus_rtu"] = "modbus_rtu"
    port: str = Field(min_length=1)  # e.g. /dev/ttyUSB0 or COM3
    baudrate: int = Field(9600, ge=1200, le=115200)
    parity: Literal["N", "E", "O"] = "N"
    stopbits: Literal[1, 2] = 1
    timeout_s: float = Field(1.0, gt=0, le=10)


class SerialTransport:
    def __init__(self, cfg: BusConfig) -> None:
        import serial  # lazy: pyserial only needed when a bus is really used

        self._ser = serial.Serial(
            cfg.port, cfg.baudrate, bytesize=8, parity=cfg.parity,
            stopbits=cfg.stopbits, timeout=cfg.timeout_s)

    def reset_input(self) -> None:
        self._ser.reset_input_buffer()

    def write(self, data: bytes) -> None:
        self._ser.write(data)
        self._ser.flush()

    def read_exact(self, n: int, timeout: float) -> bytes:
        self._ser.timeout = timeout
        data = self._ser.read(n)
        if len(data) < n:
            raise ModbusTimeout(f"no/partial response ({len(data)}/{n} bytes)")
        return data

    def close(self) -> None:
        self._ser.close()


class ModbusBus:
    """One RS485 line. Requests are serialised with a lock (one master)."""

    def __init__(self, cfg: BusConfig, transport: Transport) -> None:
        self.cfg = cfg
        self._t = transport
        self._lock = threading.Lock()
        # 3.5 character times of silence between frames (fixed 1.75 ms above 19200 baud).
        self._gap = 0.00175 if cfg.baudrate > 19200 else 3.5 * 11 / cfg.baudrate

    def read_registers(self, slave: int, function: int, register: int, count: int) -> bytes:
        req = build_read_request(slave, function, register, count)
        with self._lock:
            time.sleep(self._gap)
            self._t.reset_input()
            self._t.write(req)
            head = self._t.read_exact(3, self.cfg.timeout_s)
            if head[1] & 0x80:  # exception frame: addr, func|0x80, code, crc(2)
                rest = self._t.read_exact(2, self.cfg.timeout_s)
                frame = head + rest
                self._check_crc(frame)
                self._check_header(frame, slave, function | 0x80)
                raise ModbusException(frame[2])
            rest = self._t.read_exact(head[2] + 2, self.cfg.timeout_s)
        frame = head + rest
        self._check_crc(frame)
        self._check_header(frame, slave, function)
        if head[2] != count * 2:
            raise ModbusError(f"unexpected byte count {head[2]} (wanted {count * 2})")
        return frame[3:-2]

    def write_single_coil(self, slave: int, coil: int, on: bool) -> None:
        """Function 0x05. The device must echo the request."""
        req = with_crc(struct.pack(">BBHH", slave, 5, coil, 0xFF00 if on else 0x0000))
        with self._lock:
            time.sleep(self._gap)
            self._t.reset_input()
            self._t.write(req)
            head = self._t.read_exact(2, self.cfg.timeout_s)
            if head[1] & 0x80:
                frame = head + self._t.read_exact(3, self.cfg.timeout_s)
                self._check_crc(frame)
                self._check_header(frame, slave, 5 | 0x80)
                raise ModbusException(frame[2])
            frame = head + self._t.read_exact(6, self.cfg.timeout_s)
        self._check_crc(frame)
        if frame != req:
            raise ModbusError("device did not echo the coil write correctly")

    @staticmethod
    def _check_crc(frame: bytes) -> None:
        if struct.unpack("<H", frame[-2:])[0] != crc16(frame[:-2]):
            raise ModbusCrcError("CRC mismatch (noise, wrong baud/parity, or two devices answering)")

    @staticmethod
    def _check_header(frame: bytes, slave: int, function: int) -> None:
        if frame[0] != slave or frame[1] != function:
            raise ModbusError(f"response from slave {frame[0]} func {frame[1]}, "
                              f"expected slave {slave} func {function}")

    def close(self) -> None:
        self._t.close()


class BusManager:
    def __init__(self, transport_factory=None) -> None:
        self._factory = transport_factory or SerialTransport
        self._cfgs: dict[str, BusConfig] = {}
        self._buses: dict[str, ModbusBus] = {}
        self._lock = threading.Lock()

    def configure(self, cfgs: list[BusConfig]) -> None:
        with self._lock:
            for b in self._buses.values():
                try:
                    b.close()
                except Exception:  # noqa: BLE001
                    pass
            self._buses.clear()
            self._cfgs = {c.id: c for c in cfgs}

    def configs(self) -> list[BusConfig]:
        return list(self._cfgs.values())

    def get(self, bus_id: str) -> ModbusBus:
        with self._lock:
            if bus_id in self._buses:
                return self._buses[bus_id]
            cfg = self._cfgs.get(bus_id)
            if cfg is None:
                raise DriverError(f"bus '{bus_id}' is not configured")
            try:
                bus = ModbusBus(cfg, self._factory(cfg))
            except Exception as exc:  # port missing, permission denied...
                raise DriverError(f"cannot open {cfg.port}: {exc}") from exc
            self._buses[bus_id] = bus
            return bus

    def drop(self, bus_id: str) -> None:
        """Forget a bus after an I/O failure so the port is reopened next time."""
        with self._lock:
            b = self._buses.pop(bus_id, None)
        if b:
            try:
                b.close()
            except Exception:  # noqa: BLE001
                pass


class ModbusAddress(BaseModel):
    bus: str
    slave: int = Field(ge=1, le=247)
    function: Literal[3, 4] = 3  # 3 = holding registers, 4 = input registers
    register: int = Field(ge=0, le=65535)
    datatype: Literal["uint16", "int16", "uint32", "int32", "float32"] = "int16"
    word_order: Literal["big", "little"] = "big"
    scale: float = 1.0   # device scaling: value = raw * scale + offset (from the datasheet)
    offset: float = 0.0

    @model_validator(mode="after")
    def _fits(self):
        if self.register + DATATYPES[self.datatype] > 65536:
            raise ValueError("register range exceeds 65535")
        return self
