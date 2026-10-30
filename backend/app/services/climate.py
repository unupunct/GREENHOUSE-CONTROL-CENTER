"""Climate calculations."""

from __future__ import annotations

import math


def saturation_vapor_pressure_kpa(temp_c: float) -> float:
    """Tetens equation, valid roughly 0-50 C."""
    return 0.6108 * math.exp(17.27 * temp_c / (temp_c + 237.3))


def vpd_kpa(air_temp_c: float, rh_percent: float, leaf_temp_c: float | None = None) -> float:
    """Vapour pressure deficit in kPa.

    With ``leaf_temp_c`` omitted, leaf temperature is assumed equal to air
    temperature (a common simplification; real leaves are usually a little
    cooler or warmer depending on light and transpiration).
    """
    rh = min(max(rh_percent, 0.0), 100.0)
    leaf = air_temp_c if leaf_temp_c is None else leaf_temp_c
    return saturation_vapor_pressure_kpa(leaf) - saturation_vapor_pressure_kpa(air_temp_c) * rh / 100.0


def dew_point_c(temp_c: float, rh_percent: float) -> float:
    """Magnus formula dew point; used for condensation-risk indication."""
    rh = max(rh_percent, 0.01)
    a, b = 17.27, 237.3
    g = math.log(rh / 100.0) + a * temp_c / (b + temp_c)
    return b * g / (a - g)
