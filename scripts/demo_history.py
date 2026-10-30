"""Backfill SYNTHETIC history (3 days, one sample a minute) into a DEMO database so charts and reports have something to show.

    python scripts/demo_history.py <data folder of the demo server>

Invented numbers only. Never run it against a real installation.
"""

from __future__ import annotations

import math
import random
import sqlite3
import sys
import time
from pathlib import Path

db_path = Path(sys.argv[1]) / "greenhouse.db"
rnd = random.Random(7)
con = sqlite3.connect(db_path, timeout=30)
now = int(time.time()) // 60 * 60
first = con.execute("SELECT COALESCE(MIN(ts), ?) FROM measurements", (now,)).fetchone()[0]
sensors = {sid: kind for sid, kind in con.execute("SELECT id, kind FROM sensors WHERE simulated = 1")}
start = now - 3 * 86400


def daylight(ts: int) -> float:
    lt = time.localtime(ts)
    h = lt.tm_hour + lt.tm_min / 60
    return max(0.0, math.sin(math.pi * (h - 6) / 14)) if 6 <= h <= 20 else 0.0


def value(sid: str, kind: str, ts: int) -> float | None:
    d = daylight(ts)
    cloud = 0.55 + 0.45 * math.sin(ts / 86400 * 2.3 + 1.0) ** 2  # cloudier and clearer days
    n = rnd.gauss(0, 0.15)
    if sid in ("sim_flow_main", "sim_tank_float"):
        return None
    if kind == "temperature":
        if sid.startswith("out_"):
            return 9 + 5 * d * cloud + 2 * math.sin(ts / 86400 * 6.28) + n
        if sid.startswith("hydro"):
            return 20.5 + 1.5 * d + n * 0.3
        if sid.startswith("soil"):
            return 17 + 2 * d + n * 0.3
        return 17.5 + 10 * d * cloud + n + (0.8 if sid.endswith("2") else 0)
    if kind == "humidity":
        return (74 - 28 * d * cloud if sid.startswith("out_") else 82 - 30 * d * cloud) + n * 3
    if kind == "co2":
        return 430 + 330 * (1 - d) * 0.9 + n * 20
    if kind == "par":
        return 1250 * d * cloud + abs(n) * 5
    if kind == "soil_moisture":
        return 40 - 14 * ((ts / 3600 / 6) % 1.0) + n + (-3 if sid.endswith("2") else 0)
    if kind == "ph":
        return 5.9 + 0.08 * math.sin(ts / 3600 / 5) + n * 0.03
    if kind == "ec":
        return 1.9 + 0.12 * math.sin(ts / 3600 / 9) + n * 0.03
    if kind == "water_level":
        return 90 - 40 * ((ts / 3600 / 30) % 1.0) + n
    return None


rows = []
for sid, kind in sensors.items():
    for ts in range(start, min(first, now), 60):
        v = value(sid, kind, ts)
        if v is not None:
            rows.append((sid, ts, round(v, 3)))
con.executemany("INSERT INTO measurements (sensor_id, ts, value) VALUES (?,?,?)", rows)
con.commit()
con.close()
print(f"added {len(rows):,} synthetic samples for {len(sensors)} demo sensors")
