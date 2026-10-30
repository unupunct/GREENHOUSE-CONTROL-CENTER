"""Tiny simulated water plant so simulated outputs and sensors agree.

Pump + any open valve => flow; flow drains the simulated tank. Tests and the
demo use ``leak_lpm`` / ``tank_level_pct`` to provoke faults. Not a hydraulic model.
"""

from __future__ import annotations


class SimulatedPlant:
    def __init__(self) -> None:
        self.states: dict[str, bool] = {}
        self.kinds: dict[str, str] = {}
        self.pump_flow_lpm: dict[str, float] = {}
        self.leak_lpm = 0.0
        self.tank_level_pct = 80.0
        self.tank_capacity_l = 1000.0
        self._last = None

    def register(self, act_id: str, kind: str, flow_lpm: float = 0.0) -> None:
        self.kinds[act_id] = kind
        self.states.setdefault(act_id, False)
        if kind == "pump":
            self.pump_flow_lpm[act_id] = flow_lpm

    def set(self, act_id: str, on: bool) -> None:
        self.states[act_id] = on

    def flow_lpm(self) -> float:
        pumps = [self.pump_flow_lpm.get(i, 0.0) for i, k in self.kinds.items()
                 if k == "pump" and self.states.get(i)]
        valve_open = any(self.states.get(i) for i, k in self.kinds.items() if k == "valve")
        return (max(pumps, default=0.0) if valve_open else 0.0) + self.leak_lpm

    def advance(self, now: float) -> None:
        if self._last is not None and now > self._last:
            used = self.flow_lpm() * (now - self._last) / 60.0
            self.tank_level_pct = max(0.0, self.tank_level_pct - used / self.tank_capacity_l * 100)
        self._last = now
