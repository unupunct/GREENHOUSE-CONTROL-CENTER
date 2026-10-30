"""Pure interlock rules. No I/O, no clocks: everything is passed in, so the same
functions are exercised by unit tests and by the commissioning self-test.

These are SOFTWARE interlocks. They are a second line of defence behind
hardware protections (float switch in the pump circuit, e-stop, thermal and
current protection), never a replacement for them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TankReading:
    level_pct: float | None = None      # None = no level sensor configured
    level_age_s: float | None = None
    float_ok: float | None = None       # None = no float sensor; 1.0 = water present
    float_age_s: float | None = None
    has_level_sensor: bool = False
    has_float_sensor: bool = False


def tank_ok(t: TankReading, min_level_pct: float, max_age_s: float) -> tuple[bool, str]:
    """Fail-safe: no sensors, stale data or low water all mean NOT ok."""
    if not t.has_level_sensor and not t.has_float_sensor:
        return False, "tank has no level or float sensor configured"
    if t.has_level_sensor:
        if t.level_pct is None or t.level_age_s is None or t.level_age_s > max_age_s:
            return False, "tank level sensor has no fresh reading"
        if t.level_pct < min_level_pct:
            return False, f"tank level {t.level_pct:.0f}% is below the minimum {min_level_pct:.0f}%"
    if t.has_float_sensor:
        if t.float_ok is None or t.float_age_s is None or t.float_age_s > max_age_s:
            return False, "tank float switch has no fresh reading"
        if t.float_ok < 0.5:
            return False, "float switch reports low water"
    return True, "ok"


def start_refusals(*, kind: str, estop: bool, tank_ok_result: tuple[bool, str] | None,
                   needs_tank: bool, valve_ready_for_pump: bool, concurrent_limit_hit: bool = False) -> list[str]:
    """Reasons an output must NOT be switched on. Empty list = allowed."""
    reasons: list[str] = []
    if estop:
        reasons.append("emergency stop is latched")
    if kind == "pump":
        if needs_tank:
            ok, why = tank_ok_result if tank_ok_result is not None else (False, "no water source assigned")
            if not ok:
                reasons.append(why)
        if not valve_ready_for_pump:
            reasons.append("no open valve for this pump (dead-head protection)")
    if concurrent_limit_hit:
        reasons.append("maximum number of simultaneous zones reached")
    return reasons


def runtime_exceeded(on_since: float, now: float, max_runtime_s: float) -> bool:
    return now - on_since > max_runtime_s


def flow_violation(*, pump_running_s: float, grace_s: float, flow_lpm: float | None, flow_age_s: float | None,
                   min_lpm: float | None, max_lpm: float | None, max_age_s: float) -> str | None:
    """Reason to stop, or None. Thresholds come from the user; with none set, flow is not judged."""
    if min_lpm is None and max_lpm is None:
        return None
    if pump_running_s < grace_s:
        return None
    if flow_lpm is None or flow_age_s is None or flow_age_s > max_age_s:
        return "flow sensor has no fresh reading"
    if min_lpm is not None and flow_lpm < min_lpm:
        return f"flow {flow_lpm:.2f} L/min is below the minimum {min_lpm:g} (dry run or blockage)"
    if max_lpm is not None and flow_lpm > max_lpm:
        return f"flow {flow_lpm:.2f} L/min is above the maximum {max_lpm:g} (leak or burst pipe)"
    return None


def feedback_violation(*, on_for_s: float, grace_s: float, feedback: float | None, age_s: float | None,
                       max_age_s: float) -> str | None:
    if on_for_s < grace_s:
        return None
    if feedback is None or age_s is None or age_s > max_age_s:
        return "feedback sensor has no fresh reading"
    if feedback < 0.5:
        return "feedback reports the output is not on although it was commanded on"
    return None


def leak_suspected(*, outputs_idle: bool, flow_lpm: float | None, threshold_lpm: float | None,
                   idle_flow_s: float, confirm_s: float) -> bool:
    if threshold_lpm is None or not outputs_idle or flow_lpm is None:
        return False
    return flow_lpm > threshold_lpm and idle_flow_s >= confirm_s
