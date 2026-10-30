"""Sensor polling, in-memory aggregation and batched persistence.

Readings are sampled every ``poll_interval_s`` and held in memory. Every
``flush_interval_s`` one averaged row per sensor is written, which keeps
microSD write volume low (15 sensors -> 15 rows/minute).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass

from sqlalchemy import select

from app.core.db import Database
from app.core.models import Measurement, Sensor
from app.core.settings import Settings
from app.hal import DriverError, DriverRegistry, SensorSpec
from app.hal.simulated import default_sensor_rows
from app.services import events

log = logging.getLogger(__name__)


@dataclass
class LatestValue:
    value: float  # calibrated
    ts: int
    raw: float | None = None  # before calibration


def seed_sensors(db: Database) -> int:
    """Insert the simulated demo registry if the registry is empty."""
    with db.session() as s:
        if s.scalar(select(Sensor.id).limit(1)) is not None:
            return 0
        rows = default_sensor_rows()
        for r in rows:
            r = dict(r)
            r["address"] = json.dumps(r["address"])
            s.add(Sensor(**r))
        return len(rows)


def seed_demo_irrigation(db: Database) -> None:
    """Simulated pump/valves/tank wired to the simulated plant (demo mode only)."""
    from app.core.models import Actuator, AppSetting, Tank, Zone
    with db.session() as s:
        if s.get(AppSetting, "demo_irrigation_seeded"):
            return
        s.add(AppSetting(key="demo_irrigation_seeded", value="1", updated_at=int(time.time())))
        for sid, name, kind, unit, addr, lo, hi in [
                ("sim_flow_main", "Simulated main flow", "flow", "L/min", {"plant": "flow"}, 0, 500),
                ("sim_tank_level", "Simulated tank level", "water_level", "%", {"plant": "level"}, 0, 100),
                ("sim_tank_float", "Simulated tank float switch", "float_switch", "", {"plant": "float"}, 0, 1)]:
            s.add(Sensor(id=sid, name=name, kind=kind, zone="water", unit=unit, driver="simulated",
                         protocol="none", address=json.dumps(addr), simulated=True, min_valid=lo, max_valid=hi))
        s.add(Actuator(id="sim_pump", name="Simulated pump", kind="pump", driver="simulated_output",
                       address=json.dumps({"sim_flow_lpm": 20.0}), max_runtime_s=1800))
        s.add(Actuator(id="sim_valve_a", name="Simulated valve - soil bed A", kind="valve",
                       driver="simulated_output", address="{}", max_runtime_s=1800))
        s.add(Actuator(id="sim_valve_b", name="Simulated valve - hydroponic", kind="valve",
                       driver="simulated_output", address="{}", max_runtime_s=1800))
        s.add(Tank(id="sim_tank", name="Simulated tank", level_sensor_id="sim_tank_level",
                   float_sensor_id="sim_tank_float", min_level_pct=15.0))
        for zid, name, kind, valve in (("soil_a", "Soil bed A (demo)", "soil", "sim_valve_a"),
                                       ("hydro_1", "Hydroponic (demo)", "hydroponic", "sim_valve_b")):
            s.add(Zone(id=zid, name=name, kind=kind, valve_id=valve, pump_id="sim_pump", tank_id="sim_tank",
                       flow_sensor_id="sim_flow_main", max_duration_s=600, default_duration_s=60,
                       min_interval_s=300, expected_flow_lpm=20.0, min_flow_lpm=5.0, max_flow_lpm=40.0,
                       flow_grace_s=8))


class IngestService:
    def __init__(self, db: Database, settings: Settings, drivers: DriverRegistry) -> None:
        self.db = db
        self.settings = settings
        self.drivers = drivers
        self.latest: dict[str, LatestValue] = {}
        self._acc: dict[str, list[float]] = {}
        self._failing: set[str] = set()
        self.stats: dict[str, dict] = {}  # per-sensor communication counters (memory only)
        self._tasks: list[asyncio.Task] = []

    def _specs(self) -> list[tuple[SensorSpec, str]]:
        with self.db.session() as s:
            rows = s.scalars(select(Sensor).where(Sensor.enabled.is_(True))).all()
            return [(SensorSpec(id=r.id, kind=r.kind, zone=r.zone, unit=r.unit,
                                address=json.loads(r.address or "{}"),
                                min_valid=r.min_valid, max_valid=r.max_valid,
                                cal_offset=r.cal_offset or 0.0,
                                cal_gain=1.0 if r.cal_gain is None else r.cal_gain), r.driver)
                    for r in rows]

    async def poll_once(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        for spec, driver_name in self._specs():
            t_start = time.monotonic()
            st = self.stats.setdefault(spec.id, {"ok": 0, "fail": 0, "last_error": None, "last_ok_ts": None,
                                                 "last_fail_ts": None, "last_ms": None})
            try:
                raw = await self.drivers.get(driver_name).read(spec, now)
                value = round(spec.cal_gain * raw + spec.cal_offset, 4)
                if (spec.min_valid is not None and value < spec.min_valid) or (
                        spec.max_valid is not None and value > spec.max_valid):
                    raise DriverError(f"value {value} outside valid range "
                                      f"[{spec.min_valid}, {spec.max_valid}]")
            except Exception as exc:  # any driver failure must not stop other sensors
                st["fail"] += 1
                st["last_error"], st["last_fail_ts"] = str(exc), int(now)
                if not isinstance(exc, (DriverError, KeyError, ValueError)):
                    log.exception("unexpected driver failure for %s", spec.id)
                if spec.id not in self._failing:
                    self._failing.add(spec.id)
                    events.log_event(self.db, "error", "ingest", f"{spec.id}: {exc}")
                    events.raise_alert(self.db, "warning", "sensor_fault", spec.id,
                                       f"Sensor {spec.id} cannot be read: {exc}")
                continue
            st["ok"] += 1
            st["last_ok_ts"], st["last_ms"] = int(now), round((time.monotonic() - t_start) * 1000, 1)
            if spec.id in self._failing:
                self._failing.discard(spec.id)
                events.clear_alert(self.db, "sensor_fault", spec.id)
                events.log_event(self.db, "info", "ingest", f"{spec.id}: recovered")
            self.latest[spec.id] = LatestValue(value, int(now), raw)
            self._acc.setdefault(spec.id, []).append(value)

    def flush(self, now: float | None = None) -> int:
        """Write the mean of buffered samples per sensor. Returns rows written."""
        ts = int(time.time() if now is None else now)
        acc, self._acc = self._acc, {}
        if not acc:
            return 0
        with self.db.session() as s:
            s.add_all(Measurement(sensor_id=sid, ts=ts, value=round(sum(v) / len(v), 3))
                      for sid, v in acc.items() if v)
        return len(acc)

    def prune(self, now: float | None = None) -> int:
        from app.services import rollup
        return rollup.prune(self.db, self.settings, time.time() if now is None else now)

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self.poll_once()
            except Exception:  # keep the loop alive; the fault is logged
                log.exception("poll failed")
            await asyncio.sleep(self.settings.poll_interval_s)

    async def _flush_loop(self) -> None:
        last_prune = 0.0
        while True:
            await asyncio.sleep(self.settings.flush_interval_s)
            try:
                self.flush()
                if time.time() - last_prune > 86400:
                    self.prune()
                    last_prune = time.time()
            except Exception:
                log.exception("flush failed")

    def start(self) -> None:
        self._tasks = [asyncio.create_task(self._poll_loop()),
                       asyncio.create_task(self._flush_loop())]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        self.flush()  # don't lose the partial minute
