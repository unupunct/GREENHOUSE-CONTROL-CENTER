import pytest

from app.automation import climate_rules as cr


def test_hysteresis_greater_than():
    st = lambda v, prev: cr.threshold_state(">", 28, 26, v, prev)  # noqa: E731
    assert st(27, False) is False          # inside the band, was off: stays off
    assert st(28.5, False) is True
    assert st(27, True) is True            # inside the band, was on: stays on
    assert st(25.9, True) is False         # below the release value
    assert st(None, True) is None          # unknown input


def test_hysteresis_less_than():
    st = lambda v, prev: cr.threshold_state("<", 18, 20, v, prev)  # noqa: E731
    assert st(19, False) is False and st(17.9, False) is True
    assert st(19, True) is True and st(20.1, True) is False
    with pytest.raises(ValueError):
        cr.threshold_state("=", 1, 1, 1, False)


def test_hysteresis_validity():
    assert cr.hysteresis_valid(">", 28, 26) and cr.hysteresis_valid(">", 28, 28)
    assert not cr.hysteresis_valid(">", 28, 30)
    assert cr.hysteresis_valid("<", 18, 20) and not cr.hysteresis_valid("<", 18, 16)


def test_time_window_wraps_midnight():
    w = lambda m, s, e: cr.in_time_window(m, s, e)  # noqa: E731
    assert w(8 * 60, "06:00", "20:00") and not w(21 * 60, "06:00", "20:00")
    assert w(23 * 60, "20:00", "06:00") and w(2 * 60, "20:00", "06:00") and not w(12 * 60, "20:00", "06:00")


def test_rule_delays_and_min_times():
    rs, p = cr.RuleState(), cr.Timing(on_delay_s=10, off_delay_s=5, min_on_s=20, min_off_s=30)
    assert cr.step_rule(rs, True, 0, p) is None and not rs.active          # delay started
    assert cr.step_rule(rs, True, 9, p) is None
    assert cr.step_rule(rs, True, 10, p) == "activated"
    assert cr.step_rule(rs, False, 12, p) is None                          # off delay running
    assert cr.step_rule(rs, False, 17, p) is None                          # delay passed but min_on (20 s) not
    assert cr.step_rule(rs, False, 29, p) is None
    assert cr.step_rule(rs, False, 30, p) == "released"                    # active >= 20 s now
    assert cr.step_rule(rs, True, 31, p) is None and not rs.active         # min_off (30 s) not elapsed
    assert cr.step_rule(rs, True, 60, p) is None
    assert cr.step_rule(rs, True, 61, p) is None                           # min_off over: on_delay starts
    assert cr.step_rule(rs, True, 71, p) == "activated"


def test_flicker_does_not_activate():
    rs, p = cr.RuleState(), cr.Timing(on_delay_s=10)
    cr.step_rule(rs, True, 0, p)
    cr.step_rule(rs, False, 5, p)           # condition dropped: delay resets
    cr.step_rule(rs, True, 6, p)
    assert cr.step_rule(rs, True, 12, p) is None and not rs.active
    assert cr.step_rule(rs, True, 16, p) == "activated"


def test_max_on_forces_release_with_cooldown():
    rs, p = cr.RuleState(), cr.Timing(max_on_s=100, cooldown_s=50)
    assert cr.step_rule(rs, True, 0, p) == "activated"
    assert cr.step_rule(rs, True, 99, p) is None
    assert cr.step_rule(rs, True, 100, p) == "forced_release"
    assert cr.step_rule(rs, True, 120, p) is None and not rs.active       # cooling down
    assert cr.step_rule(rs, True, 151, p) == "activated"


def test_unknown_input_is_fail_safe():
    off = cr.Timing(on_fault="off")
    rs = cr.RuleState()
    assert cr.step_rule(rs, None, 0, off) is None and not rs.active       # never activates on unknown
    cr.step_rule(rs, True, 1, off)
    assert rs.active
    assert cr.step_rule(rs, None, 2, off) == "released"                   # unknown releases
    hold = cr.Timing(on_fault="hold")
    rs = cr.RuleState()
    cr.step_rule(rs, True, 0, hold)
    assert cr.step_rule(rs, None, 5, hold) is None and rs.active          # holds the current state


def test_combine():
    assert cr.combine("all", [True, True]) is True
    assert cr.combine("all", [True, False, None]) is False
    assert cr.combine("all", [True, None]) is None
    assert cr.combine("any", [False, True, None]) is True
    assert cr.combine("any", [False, None]) is None and cr.combine("any", [False, False]) is False
    assert cr.combine("all", []) is None


def test_priority_resolution():
    r = cr.resolve_outputs([(50, "fan", "on"), (60, "fan", "off"), (40, "heater", "on")])
    assert r["fan"] == (60, "off") and r["heater"] == (40, "on")
    assert cr.resolve_outputs([(50, "fan", "on"), (50, "fan", "off")])["fan"][1] == "off"  # tie: off wins
    assert cr.resolve_windows([(50, "w", 100), (50, "w", 30)])["w"] == (50, 30)             # tie: more closed
    assert cr.resolve_windows([(70, "w", 100), (50, "w", 0)])["w"] == (70, 100)


def _allowed(want, il, actual=(), now=1000, last_off=None, blocked=None, sensors=None, win=None):
    return cr.allowed_outputs(want, il, set(actual), now=now, last_off=last_off or {}, blocked_until=blocked or {},
                              sensor=lambda s: (sensors or {}).get(s), window_open_max_pct=win)


def test_stop_if_and_stale_safety_sensor():
    il = {"heater": {"stop_if": {"sensor_id": "t", "above": 35}}}
    assert _allowed({"heater": 50}, il, sensors={"t": 30})[0] == {"heater"}
    ok, why = _allowed({"heater": 50}, il, sensors={"t": 36})
    assert ok == set() and "safety limit" in why["heater"]
    ok, why = _allowed({"heater": 50}, il, sensors={})                      # sensor stale/missing
    assert ok == set() and "no fresh reading" in why["heater"]


def test_requires_on_resolves_in_same_tick():
    il = {"heater": {"requires_on": ["fan"]}}
    assert _allowed({"heater": 50, "fan": 50}, il)[0] == {"heater", "fan"}
    ok, why = _allowed({"heater": 50}, il)
    assert ok == set() and "requires fan" in why["heater"]
    # dependency itself refused -> dependants fall too
    il = {"heater": {"requires_on": ["fan"]}, "fan": {"stop_if": {"sensor_id": "x", "above": 1}}}
    assert _allowed({"heater": 50, "fan": 50}, il, sensors={"x": 5})[0] == set()


def test_forbids_on_higher_priority_wins():
    il = {"heater": {"forbids_on": ["cooler"]}, "cooler": {"forbids_on": ["heater"]}}
    assert _allowed({"heater": 60, "cooler": 50}, il)[0] == {"heater"}
    assert _allowed({"heater": 50, "cooler": 60}, il)[0] == {"cooler"}
    assert _allowed({"heater": 50, "cooler": 50}, il)[0] == set()           # tie: neither (fail-safe)


def test_min_off_blocked_and_window_limits():
    il = {"cooler": {"min_off_s": 300}}
    assert _allowed({"cooler": 50}, il, now=1000, last_off={"cooler": 900})[0] == set()
    assert _allowed({"cooler": 50}, il, now=1000, last_off={"cooler": 600})[0] == {"cooler"}
    assert _allowed({"cooler": 50}, il, now=1000, last_off={"cooler": 900}, actual={"cooler"})[0] == {"cooler"}  # already on
    assert _allowed({"fan": 50}, {}, now=10, blocked={"fan": 70})[0] == set()
    il = {"co2": {"windows_max_open_pct": 10}}
    assert _allowed({"co2": 50}, il, win=50)[0] == set()
    assert _allowed({"co2": 50}, il, win=5)[0] == {"co2"}


def test_hazards_fail_safe():
    h = lambda **k: cr.hazard(**{"rain": 0, "rain_configured": False, "wind": 0, "wind_configured": False,  # noqa: E731
                                 "wind_max": None, **k})
    assert h() is None
    assert h(rain=1, rain_configured=True) == "rain"
    assert "no fresh reading" in h(rain=None, rain_configured=True)
    assert h(rain=0, rain_configured=True) is None
    assert "wind above" in h(wind=12, wind_configured=True, wind_max=10)
    assert "no fresh reading" in h(wind=None, wind_configured=True, wind_max=10)
    assert h(wind=5, wind_configured=True, wind_max=10) is None


def test_move_plan():
    assert cr.move_plan(0, 50, 100, 5) == ("open", 50.0, 50)
    assert cr.move_plan(100, 0, 100, 5) == ("close", pytest.approx(110.0), 0)  # +10% overdrive at the end
    assert cr.move_plan(50, 52, 100, 5) is None                               # below minimum step
    assert cr.move_plan(98, 100, 100, 5)[0] == "open"                         # but ends are always reached
    assert cr.move_plan(100, 100, 100, 5) is None
    assert cr.move_plan(None, 40, 100, 5) == ("close", pytest.approx(110.0), 0.0)  # unknown: home first
    assert cr.move_plan(None, 100, 100, 5)[0] == "open"
    assert cr.estimate_position(0, "open", 25, 100) == 25
    assert cr.estimate_position(10, "close", 50, 100) == 0
