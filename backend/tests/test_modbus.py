import struct

import pytest

from app.hal.drivers import crc8_sensirion
from app.hal.modbus_rtu import (
    BusConfig,
    ModbusBus,
    ModbusCrcError,
    ModbusException,
    ModbusTimeout,
    build_read_request,
    decode_value,
)
from tests.fakes import FakeModbusTransport


def test_crc16_known_vector():
    # Widely published example: 01 03 00 00 00 0A -> CRC bytes C5 CD
    assert build_read_request(1, 3, 0, 10) == bytes.fromhex("010300000 00AC5CD".replace(" ", ""))


def test_crc8_sensirion_datasheet_vector():
    assert crc8_sensirion(bytes([0xBE, 0xEF])) == 0x92


def test_decode_types_and_word_order():
    assert decode_value(struct.pack(">h", -123), "int16") == -123
    assert decode_value(struct.pack(">H", 65000), "uint16") == 65000
    assert decode_value(struct.pack(">I", 100000), "uint32") == 100000
    f = struct.pack(">f", 12.5)
    assert decode_value(f, "float32") == 12.5
    swapped = f[2:] + f[:2]
    assert decode_value(swapped, "float32", "little") == 12.5


def _bus(slaves, **kw):
    cfg = BusConfig(id="b1", port="X", timeout_s=0.1)
    return ModbusBus(cfg, FakeModbusTransport(cfg, slaves, **kw))


def test_read_ok():
    bus = _bus({5: {(3, 10): 215}})
    assert struct.unpack(">H", bus.read_registers(5, 3, 10, 1))[0] == 215


def test_timeout_when_no_device():
    with pytest.raises(ModbusTimeout):
        _bus({}).read_registers(9, 3, 0, 1)


def test_crc_error_detected():
    with pytest.raises(ModbusCrcError):
        _bus({5: {(3, 0): 1}}, corrupt=[5]).read_registers(5, 3, 0, 1)


def test_exception_response():
    with pytest.raises(ModbusException) as e:
        _bus({5: {(3, 0): 1}}).read_registers(5, 3, 99, 1)
    assert e.value.code == 2 and "illegal data address" in str(e.value)
