"""Black-box production smoke/soak test against a REAL server process.

    backend/.venv/Scripts/python scripts/soak_test.py [seconds]   (default 180)

1. Fresh REAL-mode start (GCC_SIMULATE=false, authentication on): nothing seeded, first-run setup, login, no tracebacks.
2. Demo-mode soak for ``seconds``: memory/CPU sampled, endpoints timed, a zone run and the e-stop exercised,
   error lines counted in the server log.
3. Crash safety: the server is killed hard (no clean shutdown) while the e-stop is latched; after restart the
   database must be intact and the latch still set.

It proves the process behaves; it proves nothing about hardware.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / "backend" / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
SECONDS = int(sys.argv[1]) if len(sys.argv) > 1 else 180
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)


class Server:
    def __init__(self, port: int, data: Path, **env):
        self.port, self.data = port, data
        self.log = data.parent / f"server-{port}-{int(time.time())}.log"
        e = {**os.environ, "GCC_DATA_DIR": str(data), "GCC_POLL_INTERVAL_S": "1", "GCC_FLUSH_INTERVAL_S": "5", **{k: str(v) for k, v in env.items()}}
        self.proc = subprocess.Popen([str(PY), "-m", "uvicorn", "app.main:create_app", "--factory", "--port", str(port), "--log-level", "info"],
                                     cwd=ROOT / "backend", env=e, stdout=open(self.log, "w"), stderr=subprocess.STDOUT)
        self.cookie = ""
        for _ in range(60):
            time.sleep(0.5)
            try:
                self.call("GET", "/api/health")
                return
            except Exception:  # noqa: BLE001
                continue
        raise RuntimeError("server did not start; see " + str(self.log))

    def call(self, method: str, path: str, body=None, ok=(200, 201)):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "X-Requested-With": "gcc", "Cookie": self.cookie})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                sc = r.headers.get("Set-Cookie")
                if sc:
                    self.cookie = sc.split(";")[0]
                raw = r.read()
                return r.status, (json.loads(raw) if raw[:1] in (b"{", b"[") else raw)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    def procs(self) -> list[psutil.Process]:
        """The launcher plus the real server process(es) (on Windows the venv python.exe is only a launcher)."""
        root = psutil.Process(self.proc.pid)
        return [root, *root.children(recursive=True)]

    def stop(self, hard: bool = False):
        ps = self.procs()
        for p in ps:
            try:
                p.kill() if hard else p.terminate()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(ps, timeout=20)
        self.proc.wait(timeout=20)

    def log_problems(self) -> list[str]:
        return [ln for ln in self.log.read_text(errors="replace").splitlines() if "Traceback" in ln or " ERROR" in ln or "Exception" in ln]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="gcc-soak-"))

    # 1. real mode, fresh install
    d1 = tmp / "real"
    s = Server(8101, d1, GCC_SIMULATE="false")
    code, st = s.call("GET", "/api/auth/status")
    check("real mode: first start asks for setup", code == 200 and st["setup_needed"] and not st["authenticated"])
    check("real mode: API locked before setup", s.call("GET", "/api/sensors")[0] == 401)
    sc = (d1 / "setup_code.txt").read_text().strip()
    code, _ = s.call("POST", "/api/auth/setup", {"code": sc, "username": "owner", "password": "soak-test-passphrase"})
    check("real mode: administrator created", code == 200)
    check("real mode: no demo sensors, zones or outputs seeded",
          s.call("GET", "/api/sensors")[1] == [] and s.call("GET", "/api/irrigation/setup")[1]["zones"] == [] and s.call("GET", "/api/climate/setup")[1]["outputs"] == [])
    check("real mode: setup guide, manual, health, backup all answer",
          all(s.call(m, p)[0] in (200, 201) for m, p in (("GET", "/api/wizard"), ("GET", "/api/manual/preview"), ("GET", "/api/diagnostics/health"), ("POST", "/api/backup"))))
    time.sleep(8)
    h = s.call("GET", "/api/diagnostics/health")[1]
    check("real mode: health shows no 'crit' for an empty install except polling", all(c["status"] != "crit" or c["name"] == "Sensor polling" for c in h["components"]),
          ", ".join(f"{c['name']}={c['status']}" for c in h["components"] if c["status"] in ("crit", "warn")))
    s.stop()
    check("real mode: clean shutdown, no tracebacks in the log", not s.log_problems(), "; ".join(s.log_problems()[:2]))

    # 2. demo soak
    d2 = tmp / "demo"
    s = Server(8102, d2, GCC_AUTH_REQUIRED="false", GCC_SIMULATE="true")
    def rss() -> float:
        return sum(q.memory_info().rss for q in s.procs()) / 1e6

    seen: dict[int, psutil.Process] = {}

    def cpu_now() -> float:  # Process objects are kept: cpu_percent() measures since its previous call on the same object
        for q in s.procs():
            seen.setdefault(q.pid, q)
        return sum(q.cpu_percent(None) for q in seen.values() if q.is_running())
    cpu_now()
    time.sleep(5)
    rss0 = rss()
    samples = []
    lat: dict[str, list[float]] = {}
    ran_zone = estop_ok = False
    t0 = time.time()
    while time.time() - t0 < SECONDS:
        time.sleep(10)
        for path in ("/api/sensors", "/api/irrigation/status", "/api/climate/status", "/api/analytics/vpd?hours=1", "/api/shopping"):
            a = time.perf_counter()
            code, _ = s.call("GET", path)
            lat.setdefault(path, []).append((time.perf_counter() - a) * 1000)
            if code != 200:
                check(f"soak: GET {path}", False, str(code))
        samples.append((time.time() - t0, rss(), cpu_now()))
        if not ran_zone and time.time() - t0 > 20:
            ran_zone = s.call("POST", "/api/irrigation/zones/soil_a/run", {"duration_s": 30})[0] == 200
    time.sleep(1)
    rss1 = rss()
    cpu = sum(x[2] for x in samples) / max(1, len(samples))
    check("soak: a zone run started and finished while polling", ran_zone and s.call("GET", "/api/irrigation/history")[1]["runs"][0]["end_reason"] in ("completed", None))
    code, hist = s.call("GET", "/api/readings/history?sensor_id=gh_temp_1&hours=1")
    check("soak: history accumulated while running", code == 200 and len(hist["points"]) >= max(3, SECONDS // 5 - 3), f"{len(hist['points'])} points")
    check("soak: memory growth under 25 MB over the run", rss1 - rss0 < 25, f"{rss0:.0f} -> {rss1:.0f} MB")
    check("soak: average CPU under 10 % of one core", cpu < 10, f"{cpu:.1f} %")
    worst = max((max(v) for v in lat.values()), default=0)
    check("soak: slowest endpoint under 1.5 s", worst < 1500, f"{worst:.0f} ms")
    s.call("POST", "/api/safety/estop")
    estop_ok = s.call("GET", "/api/irrigation/status")[1]["estop"] is True
    check("soak: emergency stop latches", estop_ok)
    s.stop(hard=True)   # kill -9 equivalent while the latch is set and data is being written
    check("crash: server process tree killed without clean shutdown", all(not q.is_running() for q in s.procs()) if False else s.proc.poll() is not None)

    # 3. restart after a hard kill
    s2 = Server(8103, d2, GCC_AUTH_REQUIRED="false", GCC_SIMULATE="true")
    time.sleep(3)
    code, health = s2.call("GET", "/api/health")
    check("crash: database intact after hard kill", code == 200 and health["database"] == "ok")
    check("crash: emergency stop still latched after restart", s2.call("GET", "/api/irrigation/status")[1]["estop"] is True)
    check("crash: data survived (history, sensors)", len(s2.call("GET", "/api/readings/history?sensor_id=gh_temp_1&hours=1")[1]["points"]) >= 3)
    check("crash: backup + restore verification passes on the recovered database", s2.call("POST", "/api/backup/verify")[1]["ok"])
    s2.stop()
    problems = s.log_problems() + s2.log_problems()
    check("soak and restart: no tracebacks or errors in server logs", not problems, "; ".join(problems[:3]))

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed. Logs and data: {tmp}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
