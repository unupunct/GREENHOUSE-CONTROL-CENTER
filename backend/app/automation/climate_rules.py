"""Pure climate-control logic: hysteresis, rule timing, priority resolution,
equipment interlocks and window motion. No I/O or clocks; fully unit-tested.

Fail-safe stance: an unknown input never switches anything ON.
"""

from __future__ import annotations

from dataclasses import dataclass


# ------------------------------------------------------------ hysteresis
def threshold_state(op: str, on: float, off: float, value: float | None, prev: bool) -> bool | None:
    """Latching comparison. '>' becomes true above ``on`` and stays true until the
    value falls below ``off`` (off <= on). '<' mirrors it (off >= on).
    Returns None when the value is unknown."""
    if value is None:
        return None
    if op == ">":
        return (not value < off) if prev else value > on
    if op == "<":
        return (not value > off) if prev else value < on
    raise ValueError(f"bad operator {op!r}")


def hysteresis_valid(op: str, on: float, off: float) -> bool:
    return off <= on if op == ">" else off >= on


def in_time_window(minute_of_day: int, start: str, end: str) -> bool:
    """Local-time window 'HH:MM'..'HH:MM'; wraps midnight when end <= start."""
    s = int(start[:2]) * 60 + int(start[3:])
    e = int(end[:2]) * 60 + int(end[3:])
    if s == e:
        return True
    return s <= minute_of_day < e if s < e else (minute_of_day >= s or minute_of_day < e)


# ----------------------------------------------------------- rule timing
@dataclass
class RuleState:
    active: bool = False
    active_since: float = 0.0
    raw_since: float | None = None
    false_since: float | None = None
    last_release: float | None = None
    locked_until: float = 0.0


@dataclass(frozen=True)
class Timing:
    on_delay_s: float = 0
    off_delay_s: float = 0
    min_on_s: float = 0
    min_off_s: float = 0
    max_on_s: float | None = None
    cooldown_s: float = 0
    on_fault: str = "off"


def step_rule(rs: RuleState, raw: bool | None, now: float, p: Timing) -> str | None:
    """Advance one tick. ``raw`` is the combined condition (None = unknown).
    Returns 'activated', 'released', 'forced_release' or None."""
    if rs.active:
        if p.max_on_s is not None and now - rs.active_since >= p.max_on_s:
            rs.active, rs.last_release, rs.false_since = False, now, None
            rs.locked_until = now + p.cooldown_s
            return "forced_release"
        holding = raw is None and p.on_fault == "hold"
        if raw is True or holding:
            rs.false_since = None
            return None
        rs.false_since = rs.false_since if rs.false_since is not None else now
        if now - rs.false_since >= p.off_delay_s and now - rs.active_since >= p.min_on_s:
            rs.active, rs.last_release, rs.false_since = False, now, None
            return "released"
        return None
    if raw is True and now >= rs.locked_until and (rs.last_release is None or now - rs.last_release >= p.min_off_s):
        rs.raw_since = rs.raw_since if rs.raw_since is not None else now
        if now - rs.raw_since >= p.on_delay_s:
            rs.active, rs.active_since, rs.raw_since = True, now, None
            return "activated"
    else:
        rs.raw_since = None
    return None


def combine(match: str, states: list[bool | None]) -> bool | None:
    """'all': any False -> False, any unknown -> unknown. 'any': any True -> True."""
    if not states:
        return None
    if match == "all":
        if any(s is False for s in states):
            return False
        return None if any(s is None for s in states) else True
    if any(s is True for s in states):
        return True
    return None if any(s is None for s in states) else False


# ------------------------------------------------------------ resolution
def resolve_outputs(wants: list[tuple[int, str, str]]) -> dict[str, tuple[int, str]]:
    """wants: (priority, output_id, 'on'|'off'). Highest priority wins; a tie goes to OFF."""
    best: dict[str, tuple[int, str]] = {}
    for prio, out, state in wants:
        cur = best.get(out)
        if cur is None or prio > cur[0] or (prio == cur[0] and state == "off"):
            best[out] = (prio, state)
    return best


def resolve_windows(wants: list[tuple[int, str, float]]) -> dict[str, tuple[int, float]]:
    """(priority, window_id, position%). Highest priority wins; a tie goes to the more closed."""
    best: dict[str, tuple[int, float]] = {}
    for prio, win, pos in wants:
        cur = best.get(win)
        if cur is None or prio > cur[0] or (prio == cur[0] and pos < cur[1]):
            best[win] = (prio, pos)
    return best


# ----------------------------------------------------------- interlocks
def allowed_outputs(want_on: dict[str, int], interlocks: dict[str, dict], actual_on: set[str], *,
                    now: float, last_off: dict[str, float], blocked_until: dict[str, float],
                    sensor, window_open_max_pct: float | None) -> tuple[set[str], dict[str, str]]:
    """Filter requested-ON outputs through equipment interlocks.

    ``sensor(sensor_id) -> float | None`` returns a FRESH value or None.
    Returns (outputs allowed ON, {output: reason refused}). Dependencies are
    resolved against the projected state, so a heater and the fan it needs can
    start in the same tick.
    """
    cand = set(want_on)
    reasons: dict[str, str] = {}
    changed = True
    while changed:
        changed = False
        snapshot = set(cand)  # judge every output against the same state, so ties are symmetric
        for oid in sorted(snapshot):
            il = interlocks.get(oid, {})
            why = None
            if now < blocked_until.get(oid, 0):
                why = "cooling down after a forced stop"
            elif oid not in actual_on and il.get("min_off_s") and now - last_off.get(oid, -1e18) < il["min_off_s"]:
                why = f"minimum off time {il['min_off_s']}s not elapsed"
            elif il.get("stop_if"):
                si = il["stop_if"]
                v = sensor(si["sensor_id"])
                if v is None:
                    why = f"safety sensor '{si['sensor_id']}' has no fresh reading"
                elif v > si["above"]:
                    why = f"safety limit exceeded: {si['sensor_id']} {v:g} > {si['above']:g}"
            if why is None and il.get("windows_max_open_pct") is not None and window_open_max_pct is not None                     and window_open_max_pct > il["windows_max_open_pct"]:
                why = f"a window is open {window_open_max_pct:.0f}% (limit {il['windows_max_open_pct']:g}%)"
            if why is None:
                missing = [r for r in il.get("requires_on", []) if r not in snapshot]
                if missing:
                    why = f"requires {', '.join(missing)} to be on"
            if why is None:
                clash = [f for f in il.get("forbids_on", []) if f in snapshot
                         and (want_on.get(f, 0) >= want_on.get(oid, 0))]
                if clash:
                    why = f"not allowed while {', '.join(clash)} is on"
            if why:
                cand.discard(oid)
                reasons[oid] = why
                changed = True
    return cand, reasons


# --------------------------------------------------------------- windows
def hazard(*, rain: float | None, rain_configured: bool, wind: float | None, wind_configured: bool,
           wind_max: float | None) -> str | None:
    """Reason a vent must close, else None. A configured sensor with no fresh reading counts as a hazard."""
    if rain_configured and (rain is None or rain >= 0.5):
        return "rain" if rain is not None else "rain sensor has no fresh reading"
    if wind_configured and wind_max is not None and (wind is None or wind > wind_max):
        return f"wind above {wind_max:g} m/s" if wind is not None else "wind sensor has no fresh reading"
    return None


OVERDRIVE = 0.10  # extra travel time (fraction) when going to a hard end, so the end is really reached


def move_plan(pos: float | None, target: float, travel_s: float, min_step: float) -> tuple[str, float, float] | None:
    """Plan a move -> (direction 'open'|'close', run time s, position expected afterwards) or None.
    Unknown position (``None``): home against the closed end first for targets below 100."""
    if pos is None:
        if target >= 100:
            return "open", travel_s * (1 + OVERDRIVE), 100.0
        return "close", travel_s * (1 + OVERDRIVE), 0.0  # homing
    delta = target - pos
    at_end = target in (0.0, 100.0) and pos != target
    if abs(delta) < min_step and not at_end:
        return None
    if delta == 0:
        return None
    run = travel_s * abs(delta) / 100.0
    if target in (0.0, 100.0):
        run += travel_s * OVERDRIVE
    return ("open" if delta > 0 else "close"), run, target


def estimate_position(from_pos: float, direction: str, elapsed_s: float, travel_s: float) -> float:
    d = elapsed_s / travel_s * 100.0
    return max(0.0, min(100.0, from_pos + d if direction == "open" else from_pos - d))
