"""Simulated sensors.

Values come from a simple, ILLUSTRATIVE day/season model plus noise. They exist
to exercise the pipeline (storage, charts, VPD, alerts). They are not a
prediction of any real greenhouse and every simulated sensor is flagged
``simulated=True`` in the registry and UI.
"""

from __future__ import annotations

import math
import random
import time

from app.hal.base import SensorSpec


def _local_hours(now: float) -> float:
    lt = time.localtime(now)
    return lt.tm_hour + lt.tm_min / 60 + lt.tm_sec / 3600


def _outdoor_temp(now: float) -> float:
    yday = time.localtime(now).tm_yday
    seasonal = 11.0 - 13.0 * math.cos(2 * math.pi * (yday - 15) / 365)  # coldest mid-Jan
    daily = 5.0 * math.sin(2 * math.pi * (_local_hours(now) - 9) / 24)  # peak ~15:00
    return seasonal + daily


def _daylight(now: float) -> float:
    """0..1 daylight factor, 6:00-20:00."""
    h = _local_hours(now)
    if h < 6 or h > 20:
        return 0.0
    return math.sin(math.pi * (h - 6) / 14)


class SimulatedDriver:
    name = "simulated"
    label = "Simulated (demo data)"
    protocol = "none"
    kinds = None
    hardware_tested = False
    address_help = "No address needed. Optional sim_offset shifts the generated value."

    def __init__(self, ctx=None, seed: int | None = None) -> None:
        self._rng = random.Random(seed)
        self._ctx = ctx

    def validate_address(self, address: dict, kind: str) -> dict:
        return dict(address)

    def conflict_key(self, address: dict, kind: str):
        return None

    def _noise(self, scale: float) -> float:
        return self._rng.gauss(0.0, scale)

    async def read(self, spec: SensorSpec, now: float) -> float:
        out_t = _outdoor_temp(now)
        sun = _daylight(now)
        # Greenhouse runs warmer than outside by day, a little warmer at night.
        gh_t = out_t + 2.0 + 8.0 * sun
        gh_rh = 78.0 - 22.0 * sun
        offset = float(spec.address.get("sim_offset", 0.0))
        kind, zone = spec.kind, spec.zone

        plant_key = spec.address.get("plant")
        if plant_key and self._ctx is not None:  # tied to simulated outputs
            plant = self._ctx.plant
            plant.advance(now)
            if plant_key == "flow":
                return round(plant.flow_lpm(), 3)
            if plant_key == "level":
                return round(plant.tank_level_pct, 2)
            if plant_key == "float":
                return 1.0 if plant.tank_level_pct >= float(spec.address.get("min_pct", 10)) else 0.0

        if kind == "temperature":
            if zone == "outdoor":
                v = out_t + self._noise(0.15)
            elif zone == "hydroponic":
                v = 20.0 + 0.2 * (gh_t - 20.0) + self._noise(0.05)
            elif zone == "soil":
                v = 17.0 + 0.3 * (gh_t - 17.0) + self._noise(0.05)
            else:
                v = gh_t + offset + self._noise(0.15)
        elif kind == "humidity":
            if zone == "outdoor":
                v = 72.0 - 20.0 * sun + self._noise(0.8)
            else:
                v = gh_rh + offset + self._noise(0.6)
        elif kind == "co2":
            v = 430.0 + 380.0 * (1 - sun) + self._noise(6)
        elif kind == "par":
            v = 1400.0 * sun * 0.6 + self._noise(4) if sun > 0 else 0.0
        elif kind == "soil_moisture":
            # slow drying cycle, "watered" every 6 h
            phase = (now / 3600 / 6) % 1.0
            v = 38.0 - 14.0 * phase + offset + self._noise(0.3)
        elif kind == "ph":
            v = 5.9 + self._noise(0.02)
        elif kind == "ec":
            v = 1.9 + self._noise(0.02)
        elif kind == "water_level":
            v = 80.0 - 10.0 * ((now / 3600 / 12) % 1.0) + self._noise(0.2)
        else:
            v = 0.0
        return round(v, 2)


def default_sensor_rows() -> list[dict]:
    """Registry rows for the demo set. Counts/positions here are for pipeline
    testing only and are NOT hardware-planner recommendations."""

    def row(id_, name, kind, zone, unit, protocol, lo, hi, **addr):
        return dict(id=id_, name=name, kind=kind, zone=zone, unit=unit,
                    driver="simulated", protocol=protocol, simulated=True,
                    min_valid=lo, max_valid=hi, address=addr)

    return [
        row("gh_temp_1", "Air temperature - west bay", "temperature", "greenhouse", "°C", "I2C", -20, 70),
        row("gh_rh_1", "Air humidity - west bay", "humidity", "greenhouse", "%", "I2C", 0, 100),
        row("gh_temp_2", "Air temperature - east bay", "temperature", "greenhouse", "°C", "I2C", -20, 70, sim_offset=0.8),
        row("gh_rh_2", "Air humidity - east bay", "humidity", "greenhouse", "%", "I2C", 0, 100, sim_offset=-2.0),
        row("gh_co2_1", "CO2 - centre", "co2", "greenhouse", "ppm", "I2C", 0, 5000),
        row("gh_par_1", "PAR - above canopy", "par", "greenhouse", "µmol/m²/s", "RS485", 0, 3000),
        row("out_temp_1", "Outdoor temperature", "temperature", "outdoor", "°C", "1-Wire", -40, 60),
        row("out_rh_1", "Outdoor humidity", "humidity", "outdoor", "%", "I2C", 0, 100),
        row("soil_moist_1", "Soil moisture - bed A", "soil_moisture", "soil", "%", "RS485", 0, 100),
        row("soil_moist_2", "Soil moisture - bed B", "soil_moisture", "soil", "%", "RS485", 0, 100, sim_offset=-3.0),
        row("soil_temp_1", "Soil temperature - bed A", "temperature", "soil", "°C", "RS485", -10, 60),
        row("hydro_temp_1", "Nutrient solution temperature", "temperature", "hydroponic", "°C", "1-Wire", 0, 50),
        row("hydro_ph_1", "Nutrient solution pH", "ph", "hydroponic", "pH", "RS485", 0, 14),
        row("hydro_ec_1", "Nutrient solution EC", "ec", "hydroponic", "mS/cm", "RS485", 0, 10),
        row("hydro_level_1", "Nutrient tank level", "water_level", "hydroponic", "%", "RS485", 0, 100),
    ]
