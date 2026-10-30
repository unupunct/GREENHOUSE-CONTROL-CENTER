from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.hal.i2c import I2CManager
from app.hal.modbus_rtu import BusManager
from app.hal.plant import SimulatedPlant


@dataclass
class HalContext:
    """Shared hardware handles passed to drivers. Tests inject fakes here."""

    buses: BusManager = field(default_factory=BusManager)
    i2c: I2CManager = field(default_factory=I2CManager)
    w1_dir: Path = Path("/sys/bus/w1/devices")
    plant: SimulatedPlant = field(default_factory=SimulatedPlant)
