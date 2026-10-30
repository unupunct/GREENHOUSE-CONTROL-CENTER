"""Synthetic performance benchmark. Run:  backend\\.venv\\Scripts\\python scripts\\benchmark.py [days]

Builds a temporary database with 15 sensors sampled once a minute for ``days`` (default 90), then times the
operations that matter on a Raspberry Pi. Numbers from a development PC are NOT Raspberry Pi numbers: run it on
the Pi to know what it does there.
"""

from __future__ import annotations

import asyncio
import math
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("GCC_AUTH_REQUIRED", "false")

from fastapi.testclient import TestClient  # noqa: E402

from app.analytics import stats  # noqa: E402
from app.core.settings import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services import backup, rollup  # noqa: E402
from app.services.ingest import LatestValue  # noqa: E402

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 90
rows: list[tuple[str, str]] = []


def timed(label, fn, repeat=1):
    t = time.perf_counter()
    for _ in range(repeat):
        out = fn()
    dt = (time.perf_counter() - t) / repeat
    rows.append((label, f"{dt * 1000:,.1f} ms"))
    return out


def fill(path: Path, sensor_ids: list[str], days: int) -> int:
    now = int(time.time()) // 60 * 60
    start = now - days * 86400
    con = sqlite3.connect(path)
    n = 0
    for k, sid in enumerate(sensor_ids):
        def gen():
            for i, ts in enumerate(range(start, now, 60)):
                yield sid, ts, 20 + 8 * math.sin(i / 1440 * 6.28 + k) + (i % 7) / 10
        con.executemany("INSERT INTO measurements (sensor_id, ts, value) VALUES (?,?,?)", gen())
        n += (now - start) // 60
    con.commit()
    con.close()
    return n


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="gcc-bench-"))
    s = Settings(data_dir=tmp, autostart_ingest=False, autostart_engine=False, serve_frontend=False, auth_required=False,
                 retention_days=DAYS - 30)
    app = create_app(s)
    with TestClient(app) as c:
        db = app.state.db
        ids = [x["id"] for x in c.get("/api/sensors").json() if x["simulated"]][:15]
        t0 = time.perf_counter()
        n = fill(s.db_path, ids, DAYS)
        rows.append((f"insert {n:,} raw samples ({len(ids)} sensors x {DAYS} days)", f"{time.perf_counter() - t0:,.1f} s"))
        rows.append(("database size, raw only", f"{s.db_path.stat().st_size / 1e6:,.0f} MB"))

        timed("history 24 h (1 sensor)", lambda: c.get("/api/readings/history", params={"sensor_id": "gh_temp_1", "hours": 24}).json())
        timed(f"history {DAYS - 30} days, 300 points", lambda: c.get("/api/readings/history", params={"sensor_id": "gh_temp_1", "hours": 24 * (DAYS - 30), "max_points": 300}).json())
        timed("VPD history 7 days", lambda: c.get("/api/analytics/vpd", params={"hours": 168}).json())
        timed("DLI, 30 days", lambda: c.get("/api/analytics/dli", params={"days": 30}).json())
        timed("monthly report", lambda: c.get("/api/analytics/report", params={"period": "month"}).json())
        timed("monthly report as PDF", lambda: c.get("/api/analytics/report.pdf", params={"period": "month"}).content)
        timed("seasonal comparison (temperature)", lambda: c.get("/api/analytics/seasonal", params={"metric": "temperature"}).json())

        # old approach for comparison: mean across sensors computed in Python
        def py_series():
            from collections import defaultdict
            from sqlalchemy import select
            from app.core.models import Measurement
            with db.session() as se:
                r = se.execute(select(Measurement.ts, Measurement.value).where(Measurement.sensor_id.in_(ids[:2]))).all()
            acc = defaultdict(list)
            for ts, v in r:
                acc[ts].append(v)
            return {ts: sum(v) / len(v) for ts, v in acc.items()}
        timed("mean of 2 sensors over all data: Python (old)", py_series)
        timed("mean of 2 sensors over all data: SQL (now)", lambda: stats.series(db, ids[:2], 0, int(time.time()) + 1))

        n_rolled = timed("roll-up to hourly + prune old raw samples", lambda: (rollup.roll(db), app.state.ingest.prune())[1])
        rows.append(("raw samples pruned", f"{n_rolled:,}"))
        rows.append(("database size after prune (before VACUUM)", f"{s.db_path.stat().st_size / 1e6:,.0f} MB"))
        timed("history, range older than raw data (hourly roll-ups)", lambda: c.get("/api/readings/history", params={"sensor_id": "gh_temp_1", "hours": 24 * DAYS}).json())

        timed("backup now", lambda: backup.create(db, s, "manual"))
        rows.append(("backup size", f"{max(p.stat().st_size for p in (tmp / 'backups').glob('*.db')) / 1e6:,.0f} MB"))
        timed("backup + restore verification", lambda: backup.verify_roundtrip(db, s))

        # ingest flush: 15 averaged rows per minute
        ing = app.state.ingest
        asyncio.run(ing.poll_once())
        timed("one sensor poll cycle (15 simulated sensors)", lambda: asyncio.run(ing.poll_once()), repeat=20)
        timed("flush one minute of samples", lambda: (asyncio.run(ing.poll_once()), ing.flush())[1], repeat=20)

        # engine ticks: commissioning gate memo vs evaluating it every second
        eng, clim = app.state.engine, app.state.climate
        now = [1_800_000_000.0]
        eng.clock = clim.clock = lambda: now[0]
        for sid in ("sim_tank_level", "sim_tank_float", "sim_flow_main"):
            app.state.ingest.latest[sid] = LatestValue(50.0, int(now[0]), 50.0)
        c.put("/api/irrigation/settings", json={**c.get("/api/irrigation/setup").json()["settings"], "auto_enabled": True})
        c.put("/api/climate/settings", json={"auto_enabled": True, "sensor_max_age_s": 30})

        def ticks(invalidate: bool):
            for _ in range(100):
                now[0] += 1
                if invalidate:
                    eng.invalidate_gate()
                    clim.invalidate_gate()
                asyncio.run(eng.tick(now[0]))
                asyncio.run(clim.tick(now[0]))
        t = time.perf_counter(); ticks(True); old = (time.perf_counter() - t) / 100
        t = time.perf_counter(); ticks(False); new = (time.perf_counter() - t) / 100
        rows.append(("engine tick (both engines), gate evaluated every tick (old)", f"{old * 1000:,.2f} ms"))
        rows.append(("engine tick (both engines), gate memoised (now)", f"{new * 1000:,.2f} ms"))

    w = max(len(r[0]) for r in rows)
    print(f"\nBenchmark: {len(ids)} sensors x {DAYS} days, Python {sys.version.split()[0]}, {os.cpu_count()} CPUs\n")
    for k, v in rows:
        print(f"{k:<{w}}  {v:>12}")


if __name__ == "__main__":
    main()
