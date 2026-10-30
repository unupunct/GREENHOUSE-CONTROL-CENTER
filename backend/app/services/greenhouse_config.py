"""Greenhouse configuration model.

Defaults reflect the owner's stated greenhouse (10 m x 20 m, soil + hydroponics,
full automation, Romania/RON). Anything the owner has NOT stated (height,
orientation, construction, water pressure, electricity supply, ...) is ``None``
and is reported by :func:`engineering_inputs` so the UI can ask for it before
any calculation that depends on it is shown as final.
"""

from __future__ import annotations

import json
import time
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from app.core.db import Database
from app.core.models import AppSetting

CONFIG_KEY = "greenhouse"


class GrowingMethod(StrEnum):
    SOIL = "soil"
    HYDROPONIC = "hydroponic"


class AutomationLevel(StrEnum):
    MONITOR_ONLY = "monitor_only"
    ASSISTED = "assisted"
    FULL = "full"


class Orientation(StrEnum):
    NORTH_SOUTH = "north_south"  # long axis runs north-south
    EAST_WEST = "east_west"  # long axis runs east-west


class ElectricitySupply(StrEnum):
    SINGLE_PHASE_230V = "single_phase_230v"
    THREE_PHASE_400V = "three_phase_400v"
    OFF_GRID = "off_grid"


class Language(StrEnum):
    EN = "en"
    RO = "ro"


class GreenhouseConfig(BaseModel):
    name: str = "My Greenhouse"
    country: str = "Romania"
    currency: str = "RON"
    language: Language = Language.EN

    # Stated by the owner.
    length_m: float = Field(10.0, gt=0, le=500)
    width_m: float = Field(20.0, gt=0, le=500)
    growing_methods: list[GrowingMethod] = [GrowingMethod.SOIL, GrowingMethod.HYDROPONIC]
    automation_level: AutomationLevel = AutomationLevel.FULL
    controller: str = "Raspberry Pi"
    os: str = "Raspberry Pi OS 64-bit"

    # NOT stated by the owner: unknown until the wizard asks.
    height_m: float | None = Field(None, gt=0, le=20, description="Gutter/eave height")
    ridge_height_m: float | None = Field(None, gt=0, le=30)
    orientation: Orientation | None = None
    construction: str | None = None  # e.g. glass / polycarbonate / film
    heating_required: bool | None = None
    water_pressure_bar: float | None = Field(None, ge=0, le=20)
    electricity_supply: ElectricitySupply | None = None
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)

    @field_validator("growing_methods")
    @classmethod
    def _methods(cls, v: list[GrowingMethod]) -> list[GrowingMethod]:
        if not v:
            raise ValueError("at least one growing method is required")
        return sorted(set(v))

    @property
    def area_m2(self) -> float:
        return round(self.length_m * self.width_m, 2)

    @property
    def volume_m3(self) -> float | None:
        """Approximate volume (floor area x gutter height). Estimate only:
        ignores the roof space above the gutter line."""
        if self.height_m is None:
            return None
        return round(self.area_m2 * self.height_m, 2)


class EngineeringInput(BaseModel):
    key: str
    label: str
    question: str
    needed_for: list[str]
    provided: bool
    value: str | float | bool | None = None


_INPUTS: list[tuple[str, str, str, list[str]]] = [
    ("height_m", "Gutter height", "How high are the side walls (gutter/eave height) in metres?",
     ["ventilation sizing", "heating load", "air volume"]),
    ("ridge_height_m", "Ridge height", "How high is the roof ridge in metres?",
     ["ventilation geometry", "volume"]),
    ("orientation", "Orientation", "Which way does the long axis point?",
     ["shading", "lighting", "heating load"]),
    ("construction", "Construction / covering", "What is the covering (glass, polycarbonate, film)?",
     ["heating load", "light transmission", "ventilation"]),
    ("heating_required", "Heating required?", "Does the greenhouse need to be heated in winter?",
     ["heating sizing", "energy budget"]),
    ("water_pressure_bar", "Water pressure", "What is the mains/pump water pressure in bar?",
     ["irrigation design", "pump selection"]),
    ("electricity_supply", "Electricity supply", "Single-phase 230 V, three-phase 400 V, or off-grid?",
     ["electrical design", "power budget"]),
    ("latitude", "Location", "Latitude/longitude of the greenhouse (for sun and seasonal targets)?",
     ["lighting/DLI", "seasonal targets"]),
]


def engineering_inputs(cfg: GreenhouseConfig) -> list[EngineeringInput]:
    out = []
    for key, label, question, needed in _INPUTS:
        value = getattr(cfg, key)
        out.append(EngineeringInput(
            key=key, label=label, question=question, needed_for=needed,
            provided=value is not None,
            value=value.value if hasattr(value, "value") else value,
        ))
    return out


def load_config(db: Database) -> GreenhouseConfig:
    with db.session() as s:
        row = s.get(AppSetting, CONFIG_KEY)
        if row is None:
            return GreenhouseConfig()
        return GreenhouseConfig.model_validate(json.loads(row.value))


def save_config(db: Database, cfg: GreenhouseConfig) -> None:
    payload = cfg.model_dump_json()
    with db.session() as s:
        row = s.get(AppSetting, CONFIG_KEY)
        if row is None:
            s.add(AppSetting(key=CONFIG_KEY, value=payload, updated_at=int(time.time())))
        else:
            row.value = payload
            row.updated_at = int(time.time())
