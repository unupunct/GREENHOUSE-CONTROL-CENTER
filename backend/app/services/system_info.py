"""Host / Raspberry Pi compatibility and health information."""

from __future__ import annotations

import platform
import shutil
from pathlib import Path

import psutil

_MIN_PY = (3, 11)


def _pi_model() -> str | None:
    p = Path("/proc/device-tree/model")
    try:
        return p.read_bytes().rstrip(b"\x00").decode(errors="replace")
    except OSError:
        return None


def _cpu_temp_c() -> float | None:
    p = Path("/sys/class/thermal/thermal_zone0/temp")
    try:
        return int(p.read_text().strip()) / 1000.0
    except (OSError, ValueError):
        return None


def collect(data_dir: Path) -> dict:
    model = _pi_model()
    py = platform.python_version_tuple()
    py_ok = (int(py[0]), int(py[1])) >= _MIN_PY
    machine = platform.machine().lower()
    is_64 = machine in ("aarch64", "arm64", "x86_64", "amd64")
    disk = shutil.disk_usage(data_dir if data_dir.exists() else data_dir.parent)
    mem = psutil.virtual_memory()

    checks = [
        {"name": "Python >= 3.11", "ok": py_ok, "detail": platform.python_version()},
        {"name": "64-bit OS", "ok": is_64, "detail": machine},
        {"name": "Disk free >= 2 GB", "ok": disk.free >= 2 * 1024**3,
         "detail": f"{disk.free / 1024**3:.1f} GB free"},
        {"name": "RAM >= 1.5 GB", "ok": mem.total >= 1.5 * 1024**3,
         "detail": f"{mem.total / 1024**3:.1f} GB"},
    ]
    return {
        "is_raspberry_pi": model is not None,
        "pi_model": model,
        "os": f"{platform.system()} {platform.release()}",
        "machine": machine,
        "python": platform.python_version(),
        "cpu_percent": psutil.cpu_percent(interval=None),
        "cpu_temp_c": _cpu_temp_c(),
        "memory_percent": mem.percent,
        "disk_free_gb": round(disk.free / 1024**3, 1),
        "disk_total_gb": round(disk.total / 1024**3, 1),
        "uptime_s": int(__import__("time").time() - psutil.boot_time()),
        "checks": checks,
        "compatible": all(c["ok"] for c in checks),
    }
