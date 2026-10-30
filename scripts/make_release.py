"""Build the release archive (backend + prebuilt web interface + deploy files + docs), ready for `sudo ./deploy/install.sh`.

    backend/.venv/Scripts/python scripts/make_release.py        ->  dist-release/greenhouse-control-center-<version>.tar.gz

Run `npm run build` in frontend/ first (the archive contains frontend/dist so the Raspberry Pi does not need Node).
"""

from __future__ import annotations

import io
import re
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
version = re.search(r'__version__ = "([^"]+)"', (ROOT / "backend" / "app" / "__init__.py").read_text()).group(1)
if not (ROOT / "frontend" / "dist" / "index.html").exists():
    sys.exit("frontend/dist is missing: run `npm run build` in frontend/ first")
name = f"greenhouse-control-center-{version}"
out = ROOT / "dist-release"
out.mkdir(exist_ok=True)
target = out / f"{name}.tar.gz"
include = [("backend/app", True), ("backend/requirements.txt", False), ("backend/requirements.lock", False), ("backend/requirements-dev.txt", False),
           ("frontend/dist", True), ("deploy", True), ("docs", True), ("scripts", True), ("README.md", False)]
skip = ("__pycache__", ".pyc", ".pytest_cache")
with tarfile.open(target, "w:gz") as tar:
    for rel, _ in include:
        p = ROOT / rel
        for f in ([p] if p.is_file() else sorted(p.rglob("*"))):
            if f.is_file() and not any(s in f.as_posix() for s in skip):
                info = tar.gettarinfo(str(f), arcname=f"{name}/{f.relative_to(ROOT).as_posix()}")
                info.uid = info.gid = 0
                info.uname = info.gname = "root"
                if f.suffix in (".sh",) or f.name == "install.sh":
                    info.mode = 0o755
                data = f.read_bytes()
                if f.suffix in (".sh", ".service", ".py", ".md", ".txt", ".lock", ".ps1", ".json", ".html", ".css", ".js", ".ts", ".tsx") or f.name in ("install.sh",):
                    data = data.replace(bytes([13, 10]), bytes([10]))  # the Pi runs the scripts: CRLF would break them
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
print(f"{target} ({target.stat().st_size / 1e6:.1f} MB)")
