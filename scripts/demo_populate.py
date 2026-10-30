"""Fill a DEMO server (simulation mode, authentication off) with synthetic example content for screenshots and trials.

    python scripts/demo_populate.py http://127.0.0.1:8110

Everything here is invented example data (no real place, person or equipment). Never run it against a real installation.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"


def call(method: str, path: str, body=None):
    req = urllib.request.Request(BASE + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "X-Requested-With": "gcc"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]


def out(oid, name, kind, runtime=3600, **il):
    return call("POST", "/api/actuators", {"id": oid, "name": name, "kind": kind, "driver": "simulated_output", "max_runtime_s": runtime, "interlocks": il})


cfg = call("GET", "/api/config")[1]
call("PUT", "/api/config", {**cfg, "name": "Demo greenhouse", "height_m": 3.5, "ridge_height_m": 5.0, "orientation": "north_south", "construction": "polycarbonate",
                            "heating_required": True, "water_pressure_bar": 3.0, "electricity_supply": "single_phase_230v", "latitude": 44.4, "longitude": 26.1})
call("POST", "/api/crops", {"id": "tomato_a", "crop_id": "tomato", "label": "Row block A", "method": "soil", "area_m2": 60, "planted_on": "2026-09-15", "stage": "Fruiting"})
call("POST", "/api/crops/tomato_a/harvests", {"date": "2026-10-20", "quantity_kg": 38.5})

out("circ_fan", "Circulation fan", "fan")
out("exhaust_fan", "Exhaust fan", "fan")
out("heater_1", "Heater 1", "heater", requires_on=["circ_fan"], stop_if={"sensor_id": "gh_temp_1", "above": 38})
out("vent_open", "Ridge vent motor (open)", "motor", 300)
out("vent_close", "Ridge vent motor (close)", "motor", 300)
out("lamp_1", "LED lights", "light", 90000)
call("POST", "/api/climate/windows", {"id": "ridge_vent", "name": "Ridge vent", "open_output_id": "vent_open", "close_output_id": "vent_close", "travel_time_s": 90,
                                      "min_rest_s": 30})
call("POST", "/api/climate/lights", {"id": "supplement", "name": "Supplemental light", "output_ids": ["lamp_1"], "mode": "dli", "start_time": "06:00", "photoperiod_h": 16,
                                     "ppfd_sensor_id": "gh_par_1", "dli_target": 22, "on_below_ppfd": 150, "off_above_ppfd": 400})
print(call("POST", "/api/climate/templates/setpoints", {
    "temp_sensors": ["gh_temp_1", "gh_temp_2"], "day_start": "07:00", "night_start": "19:00", "heater_id": "heater_1", "circulation_fan_id": "circ_fan",
    "day_heat_on_below": 18, "day_heat_off_above": 19.5, "night_heat_on_below": 13, "night_heat_off_above": 14.5, "vent_window_ids": ["ridge_vent"],
    "vent_open_above": 26, "vent_close_below": 24, "exhaust_fan_ids": ["exhaust_fan"], "fan_on_above": 29, "fan_off_below": 27})[0])

W = {"rotation": 0, "label": "", "link": None, "layer": None}
items = [
    {"id": "bed_1", "type": "bed_soil", "x": 1.0, "y": 1.0, "w": 7.5, "h": 1.2, "label": "Soil bed A", "link": {"kind": "sensor", "id": "soil_moist_1"}},
    {"id": "bed_2", "type": "bed_soil", "x": 1.0, "y": 3.0, "w": 7.5, "h": 1.2, "label": "Soil bed B", "link": {"kind": "sensor", "id": "soil_moist_2"}},
    {"id": "hydro_1", "type": "bed_hydro", "x": 10.5, "y": 1.0, "w": 7.5, "h": 1.2, "label": "Hydroponic channels"},
    {"id": "hydro_2", "type": "bed_hydro", "x": 10.5, "y": 3.0, "w": 7.5, "h": 1.2, "label": "Hydroponic channels"},
    {"id": "walk_1", "type": "walkway", "x": 0.5, "y": 5.2, "w": 18.5, "h": 1.0, "label": "Walkway"},
    {"id": "tank_1", "type": "tank", "x": 18.2, "y": 6.8, "w": 1.5, "h": 1.5, "label": "Water tank", "link": {"kind": "tank", "id": "sim_tank"}},
    {"id": "pipe_1", "type": "pipe", "x": 1.0, "y": 6.9, "w": 17.0, "h": 0.12, "label": "Main pipe"},
    {"id": "t_west", "type": "sensor_climate", "x": 4.0, "y": 4.6, "w": 0.35, "h": 0.35, "label": "West", "link": {"kind": "sensor", "id": "gh_temp_1"}},
    {"id": "t_east", "type": "sensor_climate", "x": 14.0, "y": 4.6, "w": 0.35, "h": 0.35, "label": "East", "link": {"kind": "sensor", "id": "gh_temp_2"}},
    {"id": "fan_1", "type": "fan", "x": 19.0, "y": 3.0, "w": 0.8, "h": 0.8, "label": "Exhaust fan", "link": {"kind": "actuator", "id": "exhaust_fan"}},
    {"id": "vent_1", "type": "vent", "x": 4.0, "y": 0.1, "w": 8.0, "h": 0.25, "label": "Ridge vent", "link": {"kind": "window", "id": "ridge_vent"}},
    {"id": "light_1", "type": "light", "x": 3.0, "y": 8.4, "w": 6.0, "h": 0.3, "label": "LED lights", "link": {"kind": "actuator", "id": "lamp_1"}},
    {"id": "cab_1", "type": "cabinet", "x": 0.2, "y": 8.0, "w": 0.6, "h": 0.4, "label": "Control cabinet"},
    {"id": "door_1", "type": "door", "x": 0.0, "y": 5.3, "w": 0.3, "h": 1.2, "label": "Door"},
]
print(call("PUT", "/api/layout", {"items": [{**W, **i} for i in items], "grid_m": 0.5})[0])
print("demo content added")
