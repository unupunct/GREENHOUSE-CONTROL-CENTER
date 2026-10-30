from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class DriverError(Exception):
    """Raised when a sensor cannot be read (bus error, timeout, bad CRC...)."""


@dataclass(frozen=True)
class SensorSpec:
    """Driver-facing view of a registry row."""

    id: str
    kind: str
    zone: str
    unit: str
    address: dict = field(default_factory=dict)
    min_valid: float | None = None
    max_valid: float | None = None
    cal_offset: float = 0.0
    cal_gain: float = 1.0


@dataclass(frozen=True)
class Reading:
    sensor_id: str
    value: float
    ts: int


class SensorDriver(Protocol):
    name: str
    label: str
    protocol: str
    kinds: tuple[str, ...] | None  # None = any
    hardware_tested: bool
    address_help: str

    def validate_address(self, address: dict, kind: str) -> dict:
        """Return the normalised address or raise ValueError."""
        ...

    def conflict_key(self, address: dict, kind: str) -> tuple | None:
        """Two registry rows with the same key address the same measurement."""
        ...

    async def read(self, spec: SensorSpec, now: float) -> float:
        """Return a RAW measurement in ``spec.unit`` or raise :class:`DriverError`.
        Calibration is applied by the caller."""
        ...
