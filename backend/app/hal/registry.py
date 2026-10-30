from __future__ import annotations

from app.hal.base import SensorDriver
from app.hal.context import HalContext
from app.hal.drivers import Ds18b20Driver, GpioInputDriver, ModbusRtuDriver, Sht3xDriver
from app.hal.simulated import SimulatedDriver

DRIVERS: dict[str, type] = {
    cls.name: cls for cls in (SimulatedDriver, ModbusRtuDriver, Ds18b20Driver, Sht3xDriver, GpioInputDriver)
}


class DriverRegistry:
    """Instantiates each driver once (drivers may hold caches/handles)."""

    def __init__(self, ctx: HalContext) -> None:
        self.ctx = ctx
        self._inst: dict[str, SensorDriver] = {}

    def get(self, name: str) -> SensorDriver:
        if name not in self._inst:
            try:
                cls = DRIVERS[name]
            except KeyError:
                raise KeyError(f"no driver registered for '{name}'") from None
            self._inst[name] = cls(self.ctx)
        return self._inst[name]

    def describe(self) -> list[dict]:
        out = []
        for name, cls in DRIVERS.items():
            out.append({"name": name, "label": cls.label, "protocol": cls.protocol,
                        "kinds": list(cls.kinds) if cls.kinds else None,
                        "hardware_tested": cls.hardware_tested,
                        "address_help": cls.address_help})
        return out
