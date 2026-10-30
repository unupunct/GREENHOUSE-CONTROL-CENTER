"""Hardware registry, bus configuration, test reads, calibration."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from app.core.models import AppSetting, Calibration, Sensor
from app.hal import DriverError, SensorSpec
from app.hal.modbus_rtu import (
    BusConfig,
    ModbusCrcError,
    ModbusException,
    ModbusTimeout,
)
from app.services import calibration as cal
from app.services import events

router = APIRouter(prefix="/api")

BUSES_KEY = "buses"
KINDS = ["temperature", "humidity", "co2", "par", "light", "soil_moisture", "soil_ec", "ph", "ec",
         "water_level", "float_switch", "flow", "pressure", "leaf_wetness", "other"]
ZONES = ["greenhouse", "outdoor", "soil", "hydroponic", "water", "other"]


def _db(r: Request):
    return r.app.state.db


def load_buses(db) -> list[BusConfig]:
    with db.session() as s:
        row = s.get(AppSetting, BUSES_KEY)
        return [BusConfig.model_validate(b) for b in json.loads(row.value)] if row else []


# ---------------------------------------------------------------- drivers

@router.get("/hardware/drivers")
def drivers(request: Request):
    return {"drivers": request.app.state.drivers.describe(), "kinds": KINDS, "zones": ZONES}


@router.get("/hardware/1wire/devices")
def w1_devices(request: Request):
    return {"devices": request.app.state.drivers.get("ds18b20").list_devices()}


@router.get("/hardware/serial-ports")
def serial_ports():
    try:
        from serial.tools import list_ports
        return {"ports": [{"device": p.device, "description": p.description}
                          for p in list_ports.comports()]}
    except Exception:  # noqa: BLE001
        return {"ports": []}


# ------------------------------------------------------------------ buses

@router.get("/hardware/buses")
def get_buses(request: Request):
    return [b.model_dump() for b in load_buses(_db(request))]


@router.put("/hardware/buses")
def put_buses(buses: list[BusConfig], request: Request):
    ids = [b.id for b in buses]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, "bus ids must be unique")
    ports = [b.port for b in buses]
    if len(ports) != len(set(ports)):
        raise HTTPException(422, "two buses cannot share one serial port")
    with _db(request).session() as s:
        row = s.get(AppSetting, BUSES_KEY)
        payload = json.dumps([b.model_dump() for b in buses])
        if row is None:
            s.add(AppSetting(key=BUSES_KEY, value=payload, updated_at=int(time.time())))
        else:
            row.value, row.updated_at = payload, int(time.time())
    request.app.state.ctx.buses.configure(buses)
    events.log_event(_db(request), "info", "hardware", f"Bus configuration updated ({len(buses)} bus(es))")
    return [b.model_dump() for b in buses]


class ScanRequest(BaseModel):
    start: int = Field(1, ge=1, le=247)
    end: int = Field(10, ge=1, le=247)
    function: Literal[3, 4] = 3
    register: int = Field(0, ge=0, le=65535)


@router.post("/hardware/buses/{bus_id}/scan")
async def scan_bus(bus_id: str, body: ScanRequest, request: Request):
    """Probe slave addresses by reading ONE register (you choose which; use one
    that exists on your device). Read-only. Limited to 32 addresses per call
    because every silent address costs a full timeout. Pauses polling on this bus."""
    if body.end < body.start or body.end - body.start >= 32:
        raise HTTPException(422, "scan at most 32 consecutive addresses per request")
    try:
        bus = request.app.state.ctx.buses.get(bus_id)
    except DriverError as exc:
        raise HTTPException(400, str(exc)) from exc

    def run():
        out = []
        for addr in range(body.start, body.end + 1):
            try:
                data = bus.read_registers(addr, body.function, body.register, 1)
                out.append({"slave": addr, "result": "responded", "raw_hex": data.hex()})
            except ModbusException as e:
                out.append({"slave": addr, "result": "responded_with_exception", "detail": str(e)})
            except ModbusCrcError as e:
                out.append({"slave": addr, "result": "crc_error",
                            "detail": f"{e}. If this repeats, suspect two devices with the same address."})
            except ModbusTimeout:
                pass  # silence: nothing at this address
            except DriverError as e:
                out.append({"slave": addr, "result": "error", "detail": str(e)})
        return out

    found = await asyncio.to_thread(run)
    return {"bus": bus_id, "scanned": [body.start, body.end], "found": found}


# ---------------------------------------------------------------- sensors

class SensorIn(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]{2,48}$")
    name: str = Field(min_length=1, max_length=120)
    kind: str
    zone: str
    unit: str = Field(min_length=1, max_length=16)
    driver: str
    address: dict = {}
    min_valid: float | None = None
    max_valid: float | None = None
    enabled: bool = True


def _row_dict(r: Sensor) -> dict:
    return {"id": r.id, "name": r.name, "kind": r.kind, "zone": r.zone, "unit": r.unit,
            "driver": r.driver, "protocol": r.protocol, "simulated": r.simulated,
            "enabled": r.enabled, "address": json.loads(r.address or "{}"),
            "min_valid": r.min_valid, "max_valid": r.max_valid,
            "cal_offset": r.cal_offset, "cal_gain": r.cal_gain, "calibrated_at": r.calibrated_at}


def _validated(body: SensorIn, request: Request, existing_id: str | None) -> tuple[dict, str]:
    reg = request.app.state.drivers
    try:
        drv = reg.get(body.driver)
    except KeyError:
        raise HTTPException(422, f"unknown driver '{body.driver}'") from None
    if drv.kinds and body.kind not in drv.kinds:
        raise HTTPException(422, f"driver '{body.driver}' only supports kinds {list(drv.kinds)}")
    try:
        addr = drv.validate_address(body.address, body.kind)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(422, f"invalid address for driver '{body.driver}': {exc}") from exc
    key = drv.conflict_key(addr, body.kind)
    if key is not None:
        with _db(request).session() as s:
            for o in s.scalars(select(Sensor).where(Sensor.driver == body.driver)):
                if o.id == existing_id:
                    continue
                if drv.conflict_key(json.loads(o.address or "{}"), o.kind) == key:
                    raise HTTPException(409, f"address conflict: sensor '{o.id}' already reads this "
                                             "same bus address")
    return addr, drv.protocol


@router.post("/sensors", status_code=201)
def create_sensor(body: SensorIn, request: Request):
    addr, proto = _validated(body, request, None)
    with _db(request).session() as s:
        if s.get(Sensor, body.id):
            raise HTTPException(409, f"sensor id '{body.id}' already exists")
        s.add(Sensor(id=body.id, name=body.name, kind=body.kind, zone=body.zone, unit=body.unit,
                     driver=body.driver, protocol=proto, address=json.dumps(addr),
                     simulated=body.driver == "simulated", enabled=body.enabled,
                     min_valid=body.min_valid, max_valid=body.max_valid))
    events.log_event(_db(request), "info", "hardware", f"Sensor '{body.id}' added ({body.driver})")
    return {"id": body.id}


@router.put("/sensors/{sensor_id}")
def update_sensor(sensor_id: str, body: SensorIn, request: Request):
    if body.id != sensor_id:
        raise HTTPException(422, "the sensor id cannot be changed")
    addr, proto = _validated(body, request, sensor_id)
    with _db(request).session() as s:
        r = s.get(Sensor, sensor_id)
        if r is None:
            raise HTTPException(404, "sensor not found")
        r.name, r.kind, r.zone, r.unit = body.name, body.kind, body.zone, body.unit
        r.driver, r.protocol, r.address = body.driver, proto, json.dumps(addr)
        r.simulated = body.driver == "simulated"
        r.enabled, r.min_valid, r.max_valid = body.enabled, body.min_valid, body.max_valid
    request.app.state.ingest.latest.pop(sensor_id, None)
    return {"ok": True}


@router.delete("/sensors/{sensor_id}")
def delete_sensor(sensor_id: str, request: Request):
    """Deletes the sensor AND its stored measurements and calibration history."""
    with _db(request).session() as s:
        r = s.get(Sensor, sensor_id)
        if r is None:
            raise HTTPException(404, "sensor not found")
        s.delete(r)
        from sqlalchemy import delete as _delete
        from app.core.models import MeasurementHourly
        s.execute(_delete(MeasurementHourly).where(MeasurementHourly.sensor_id == sensor_id))
    request.app.state.ingest.latest.pop(sensor_id, None)
    events.log_event(_db(request), "warning", "hardware", f"Sensor '{sensor_id}' deleted with its history")
    return {"ok": True}


@router.post("/sensors/{sensor_id}/test-read")
async def test_read(sensor_id: str, request: Request):
    """One live read; nothing is stored."""
    with _db(request).session() as s:
        r = s.get(Sensor, sensor_id)
        if r is None:
            raise HTTPException(404, "sensor not found")
        spec = SensorSpec(id=r.id, kind=r.kind, zone=r.zone, unit=r.unit,
                          address=json.loads(r.address or "{}"), cal_offset=r.cal_offset or 0.0,
                          cal_gain=1.0 if r.cal_gain is None else r.cal_gain)
        driver = r.driver
    t0 = time.monotonic()
    try:
        raw = await request.app.state.drivers.get(driver).read(spec, time.time())
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "raw": raw, "calibrated": round(spec.cal_gain * raw + spec.cal_offset, 4),
            "unit": spec.unit, "elapsed_ms": int((time.monotonic() - t0) * 1000)}


# ------------------------------------------------------------ calibration

class CalibrationIn(BaseModel):
    method: Literal["manual", "one_point", "two_point", "reset"]
    note: str = ""
    # manual
    gain: float | None = None
    offset: float | None = None
    # one_point: uses the latest raw reading unless raw1 is given
    reference: float | None = None
    raw1: float | None = None
    ref1: float | None = None
    raw2: float | None = None
    ref2: float | None = None


@router.post("/sensors/{sensor_id}/calibration")
def calibrate(sensor_id: str, body: CalibrationIn, request: Request):
    with _db(request).session() as s:
        r = s.get(Sensor, sensor_id)
        if r is None:
            raise HTTPException(404, "sensor not found")
        cur_gain = 1.0 if r.cal_gain is None else r.cal_gain
    try:
        if body.method == "reset":
            gain, offset = 1.0, 0.0
        elif body.method == "manual":
            if body.gain is None or body.offset is None:
                raise cal.CalibrationError("manual calibration needs gain and offset")
            gain, offset = body.gain, body.offset
        elif body.method == "one_point":
            raw = body.raw1
            if raw is None:
                lv = request.app.state.ingest.latest.get(sensor_id)
                if lv is None or lv.raw is None:
                    raise cal.CalibrationError("no live reading available; supply raw1 explicitly")
                raw = lv.raw
            if body.reference is None:
                raise cal.CalibrationError("one-point calibration needs 'reference'")
            gain, offset = cal.one_point(raw, body.reference, cur_gain)
        else:
            if None in (body.raw1, body.ref1, body.raw2, body.ref2):
                raise cal.CalibrationError("two-point calibration needs raw1, ref1, raw2, ref2")
            gain, offset = cal.two_point(body.raw1, body.ref1, body.raw2, body.ref2)  # type: ignore[arg-type]
        cal.apply(_db(request), sensor_id, gain, offset, body.method, body.note)
    except cal.CalibrationError as exc:
        raise HTTPException(422, str(exc)) from exc
    events.log_event(_db(request), "info", "calibration",
                     f"{sensor_id}: {body.method} gain={gain:.4f} offset={offset:.4f}")
    return {"gain": gain, "offset": offset}


@router.get("/sensors/{sensor_id}/calibration")
def calibration_history(sensor_id: str, request: Request):
    with _db(request).session() as s:
        if s.get(Sensor, sensor_id) is None:
            raise HTTPException(404, "sensor not found")
        rows = s.scalars(select(Calibration).where(Calibration.sensor_id == sensor_id)
                         .order_by(Calibration.id.desc())).all()
    return [{"ts": c.ts, "method": c.method, "gain": c.gain, "offset": c.offset, "note": c.note}
            for c in rows]
