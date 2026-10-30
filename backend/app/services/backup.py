"""Backup, verification and restore of the SQLite database.

* Backups use SQLite's online backup API: consistent while the application runs.
* Every backup is integrity-checked, checksummed and described by a manifest.
* A backup contains EVERYTHING, including user password hashes: treat the files as secret.
* Restore verifies the file first, takes a "pre-restore" backup of the current data, switches every
  output off, then copies the backup into the live database and reloads the engines.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy import select

from app import __version__
from app.core.db import Database
from app.core.models import AppSetting
from app.services import events

MAGIC = b"SQLite format 3\x00"
REQUIRED_TABLES = {"app_settings", "sensors", "measurements", "events", "alerts", "users", "actuators", "zones"}
CONFIG_TABLES = ["app_settings", "sensors", "actuators", "tanks", "zones", "climate_rules", "windows", "light_programs", "users",
                 "crop_batches", "maintenance_tasks", "offers"]
COUNT_TABLES = CONFIG_TABLES + ["measurements", "measurement_hourly", "events", "alerts", "irrigation_runs", "audit_log"]
KEEP_LABELS = ("auto", "manual")
SETTINGS_KEY = "backup"


class BackupSettings(BaseModel):
    enabled: bool = True
    time: str = Field("03:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    keep: int = Field(7, ge=1, le=365)
    copy_dir: str | None = Field(None, max_length=300)  # e.g. a mounted USB drive or NAS share



def load_settings(db: Database) -> BackupSettings:
    with db.session() as s:
        row = s.get(AppSetting, SETTINGS_KEY)
        return BackupSettings.model_validate(json.loads(row.value)) if row else BackupSettings()


def save_settings(db: Database, b: BackupSettings) -> None:
    with db.session() as s:
        row = s.get(AppSetting, SETTINGS_KEY)
        payload = b.model_dump_json()
        if row is None:
            s.add(AppSetting(key=SETTINGS_KEY, value=payload, updated_at=int(time.time())))
        else:
            row.value, row.updated_at = payload, int(time.time())


def backup_dir(settings) -> Path:
    d = settings.data_dir / "backups"
    d.mkdir(parents=True, exist_ok=True)
    try:
        d.chmod(0o700)
    except OSError:
        pass
    return d


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _counts(path: Path, tables: list[str]) -> dict[str, int | None]:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {t: (con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] if t in have else None) for t in tables}  # noqa: S608 (fixed table list)
    finally:
        con.close()


def verify_file(path: Path) -> dict:
    """Is this file a usable backup? Never raises."""
    problems: list[str] = []
    rows: dict = {}
    try:
        if not path.is_file() or path.stat().st_size < 4096:
            return {"ok": False, "problems": ["file is missing or too small to be a database"], "rows": {}}
        with path.open("rb") as f:
            if f.read(16) != MAGIC:
                return {"ok": False, "problems": ["not a SQLite database file"], "rows": {}}
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            res = con.execute("PRAGMA integrity_check").fetchone()[0]
            if res != "ok":
                problems.append(f"integrity check failed: {res}")
            have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            con.close()
        missing = REQUIRED_TABLES - have
        if missing:
            problems.append(f"missing tables: {sorted(missing)} (not a Greenhouse Control Center backup?)")
        if not problems:
            rows = _counts(path, COUNT_TABLES)
        man = path.with_suffix(".json")
        if man.exists():
            try:
                m = json.loads(man.read_text())
                if m.get("sha256") and m["sha256"] != _sha256(path):
                    problems.append("checksum differs from the manifest: the file changed after it was written")
            except ValueError:
                problems.append("manifest is unreadable")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"cannot open: {exc}")
    return {"ok": not problems, "problems": problems, "rows": rows}


def create(db: Database, settings, label: str = "manual", now: float | None = None) -> dict:
    now = time.time() if now is None else now
    d = backup_dir(settings)
    size = settings.db_path.stat().st_size if settings.db_path.exists() else 0
    if shutil.disk_usage(d).free < 2 * size + 10_000_000:
        raise OSError("not enough free disk space for a backup")
    stem = f"greenhouse-{time.strftime('%Y%m%d-%H%M%S', time.localtime(now))}-{label}"
    name, n = stem + ".db", 1
    while (d / name).exists():  # never overwrite an existing backup (e.g. two restores in the same second)
        n += 1
        name = f"{stem}-{n}.db"
    final, tmp = d / name, d / (name + ".part")
    src = sqlite3.connect(db.path)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    v = verify_file(tmp)
    if not v["ok"]:
        tmp.unlink(missing_ok=True)
        raise OSError("backup failed its own integrity check: " + "; ".join(v["problems"]))
    os.replace(tmp, final)
    try:
        final.chmod(0o600)
    except OSError:
        pass
    man = {"name": name, "label": label, "created_ts": int(now), "size": final.stat().st_size, "sha256": _sha256(final),
           "app_version": __version__, "rows": v["rows"]}
    final.with_suffix(".json").write_text(json.dumps(man))
    return man


def list_backups(settings) -> list[dict]:
    out = []
    for m in sorted(backup_dir(settings).glob("greenhouse-*.json"), reverse=True):
        try:
            man = json.loads(m.read_text())
        except ValueError:
            continue
        if (m.with_suffix(".db")).exists():
            out.append(man)
    return sorted(out, key=lambda x: -x["created_ts"])


def prune(settings, keep: int) -> list[str]:
    removed = []
    mans = list_backups(settings)
    for label, n in (("auto", keep), ("manual", keep), ("pre-restore", 5)):
        for man in [m for m in mans if m["label"] == label][n:]:
            delete(settings, man["name"])
            removed.append(man["name"])
    return removed


def path_of(settings, name: str) -> Path | None:
    """Resolve a backup name safely (no path traversal)."""
    if not name.startswith("greenhouse-") or not name.endswith(".db") or "/" in name or "\\" in name or ".." in name:
        return None
    p = backup_dir(settings) / name
    return p if p.is_file() else None


def delete(settings, name: str) -> bool:
    p = path_of(settings, name)
    if p is None:
        return False
    p.unlink(missing_ok=True)
    p.with_suffix(".json").unlink(missing_ok=True)
    return True


def copy_offsite(settings, bset: BackupSettings, man: dict) -> str | None:
    """Copy to the extra folder (USB/NAS). Returns an error text or None."""
    if not bset.copy_dir:
        return None
    try:
        src = backup_dir(settings) / man["name"]
        shutil.copy2(src, Path(bset.copy_dir) / man["name"])
        shutil.copy2(src.with_suffix(".json"), Path(bset.copy_dir) / (man["name"][:-3] + ".json"))
        return None
    except OSError as exc:
        return str(exc)


def last_backup(settings) -> dict | None:
    for m in list_backups(settings):
        if m["label"] in KEEP_LABELS:
            return m
    return None


def run_scheduled(app, now: float | None = None) -> dict | None:
    """Daily backup at the configured time; raises an alert on failure."""
    now = time.time() if now is None else now
    db, settings = app.state.db, app.state.settings
    b = load_settings(db)
    if not b.enabled:
        return None
    last = last_backup(settings)
    lt = time.localtime(now)
    due_min = int(b.time[:2]) * 60 + int(b.time[3:])
    if lt.tm_hour * 60 + lt.tm_min < due_min or (last and now - last["created_ts"] < 20 * 3600):
        return None
    try:
        man = create(db, settings, "auto", now)
        err = copy_offsite(settings, b, man)
        prune(settings, b.keep)
        if err:
            events.raise_alert(db, "warning", "backup_failed", "copy", f"Backup made, but the copy to {b.copy_dir} failed: {err}")
        else:
            events.clear_alert(db, "backup_failed", "copy")
        events.clear_alert(db, "backup_failed", "local")
        events.log_event(db, "info", "backup", f"Scheduled backup {man['name']} ({man['size'] // 1024} KB)")
        return man
    except Exception as exc:  # noqa: BLE001
        events.raise_alert(db, "critical", "backup_failed", "local", f"Scheduled backup failed: {exc}")
        return None


def verify_roundtrip(db: Database, settings) -> dict:
    """Automated test: back up, verify the file, open a COPY as a database and read it back."""
    t0 = time.time()
    problems: list[str] = []
    man = None
    tmpdir = Path(tempfile.mkdtemp(prefix="verify-", dir=backup_dir(settings)))
    try:
        man = create(db, settings, "verify")
        path = backup_dir(settings) / man["name"]
        v = verify_file(path)
        problems += v["problems"]
        trial = tmpdir / "trial.db"
        shutil.copy2(path, trial)
        t = Database(trial)
        try:
            if t.integrity_check() != "ok":
                problems.append("restored copy failed its integrity check")
            from app.services.greenhouse_config import load_config
            load_config(t)
            with t.session() as s:
                n = len(list(s.scalars(select(AppSetting.key))))
            live = len(list(db_keys(db)))
            if n < live - 2:
                problems.append("restored copy is missing settings present in the live database")
        finally:
            t.dispose()
        for tbl in CONFIG_TABLES:
            if tbl in ("app_settings", "users", "offers"):
                continue
            a, b = man["rows"].get(tbl), _counts(settings.db_path, [tbl])[tbl]
            if a is not None and b is not None and a != b:
                problems.append(f"table {tbl}: backup has {a} rows, live database {b}")
    except Exception as exc:  # noqa: BLE001
        problems.append(str(exc))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        if man:
            delete(settings, man["name"])
    return {"ok": not problems, "problems": problems, "seconds": round(time.time() - t0, 2),
            "detail": "backup written, checksum and integrity verified, restored copy opened and read back" if not problems else "; ".join(problems)}


def db_keys(db: Database):
    with db.session() as s:
        return list(s.scalars(select(AppSetting.key)))


def _keep_audit_continuity(db: Database, pre_restore: Path) -> int:
    """The audit trail must not be rolled back by a restore: bring over the entries newer than the restored copy."""
    con = sqlite3.connect(db.path, timeout=30)
    try:
        con.execute("ATTACH DATABASE ? AS pre", (pre_restore.as_posix(),))
        cur = con.execute(
            "INSERT INTO main.audit_log (id, ts, username, role, ip, method, path, status, detail) "
            "SELECT id, ts, username, role, ip, method, path, status, detail FROM pre.audit_log "
            "WHERE id > (SELECT COALESCE(MAX(id), 0) FROM main.audit_log) ORDER BY id")
        con.commit()
        return cur.rowcount or 0
    except sqlite3.Error:
        return 0
    finally:
        con.close()


async def restore(app, path: Path) -> dict:
    st = app.state
    v = verify_file(path)
    if not v["ok"]:
        raise ValueError("; ".join(v["problems"]))
    pre = create(st.db, st.settings, "pre-restore")
    await st.engine.shutdown()   # every output OFF before the data under it changes
    await st.climate.shutdown()
    src = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(st.db.path, timeout=30)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    st.db.engine.dispose()
    st.db.create_all()          # tables newer than the backup are created empty
    _keep_audit_continuity(st.db, backup_dir(st.settings) / pre["name"])
    st.ingest.latest.clear()
    st.engine.jobs.clear()       # nothing from before the restore may keep running
    st.engine.holds.clear()
    st.climate.holds.clear()
    st.climate.win_holds.clear()
    st.engine.reload()
    st.climate.reload()
    events.log_event(st.db, "warning", "backup", f"Database restored from {path.name}; previous data saved as {pre['name']}")
    return {"restored_from": path.name, "pre_restore_backup": pre["name"], "rows": v["rows"]}
