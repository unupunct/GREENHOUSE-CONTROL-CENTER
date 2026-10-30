"""Hardware abstraction layer.

Drivers implement :class:`SensorDriver`. The rest of the application only sees
values, never bus details.
"""

from app.hal.base import DriverError, Reading, SensorDriver, SensorSpec
from app.hal.context import HalContext
from app.hal.registry import DRIVERS, DriverRegistry

__all__ = ["DRIVERS", "DriverError", "DriverRegistry", "HalContext", "Reading",
           "SensorDriver", "SensorSpec"]
