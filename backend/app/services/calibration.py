"""Linear sensor calibration: calibrated = gain * raw + offset.

"raw" is the value after the driver's own datasheet scaling but before any
calibration. Calibration is a user action against a reference instrument or a
known reference solution; this module only does the arithmetic and bookkeeping.
"""

from __future__ import annotations

import time

from app.core.db import Database
from app.core.models import Calibration, Sensor


class CalibrationError(ValueError):
    pass


def one_point(raw: float, reference: float, gain: float = 1.0) -> tuple[float, float]:
    """Offset-only correction keeping the existing gain."""
    return gain, reference - gain * raw


def two_point(raw1: float, ref1: float, raw2: float, ref2: float) -> tuple[float, float]:
    if abs(raw2 - raw1) < 1e-9:
        raise CalibrationError("the two raw readings are identical; use two different reference points")
    if abs(ref2 - ref1) < 1e-9:
        raise CalibrationError("the two reference values are identical")
    gain = (ref2 - ref1) / (raw2 - raw1)
    if gain <= 0:
        raise CalibrationError("gain would be zero or negative: readings and references disagree in direction")
    return gain, ref1 - gain * raw1


def apply(db: Database, sensor_id: str, gain: float, offset: float, method: str, note: str = "") -> None:
    if not 0.1 <= gain <= 10:
        raise CalibrationError(f"gain {gain:.3f} is outside the sane range 0.1-10; check the inputs")
    now = int(time.time())
    with db.session() as s:
        sensor = s.get(Sensor, sensor_id)
        if sensor is None:
            raise KeyError(sensor_id)
        sensor.cal_gain, sensor.cal_offset, sensor.calibrated_at = gain, offset, now
        s.add(Calibration(sensor_id=sensor_id, ts=now, method=method, offset=offset, gain=gain, note=note))
