import asyncio
import gzip
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

from sqlalchemy import select

from app.core.models import Measurement
from app.services import backup as bk


def _make(client):
    r = client.post("/api/backup")
    assert r.status_code == 201, r.text
    return r.json()


def _cfg(client, **kw):
    c = client.get("/api/config").json()
    c.update(kw)
    assert client.put("/api/config", json=c).status_code == 200


def _dir(client) -> Path:
    return bk.backup_dir(client.app.state.settings)


def test_backup_is_consistent_verified_and_private(client):
    man = _make(client)
    p = _dir(client) / man["name"]
    assert p.is_file() and man["size"] == p.stat().st_size and len(man["sha256"]) == 64 and man["label"] == "manual"
    assert man["rows"]["sensors"] >= 15 and man["rows"]["app_settings"] > 0
    v = bk.verify_file(p)
    assert v["ok"] and v["problems"] == []
    if os.name == "posix":
        assert oct(p.stat().st_mode & 0o777) == "0o600"
    ov = client.get("/api/backup").json()
    assert ov["backups"][0]["name"] == man["name"] and "password hashes" in ov["warning"] and ov["free_gb"] > 0
    assert not list(_dir(client).glob("*.part"))                                    # no half-written files left


def test_corrupt_and_foreign_files_are_refused(client, tmp_path):
    man = _make(client)
    p = _dir(client) / man["name"]
    bad = tmp_path / "x.db"
    bad.write_bytes(b"not a database at all" * 1000)
    assert not bk.verify_file(bad)["ok"] and "not a SQLite" in bk.verify_file(bad)["problems"][0]
    assert not bk.verify_file(tmp_path / "missing.db")["ok"]
    tiny = tmp_path / "tiny.db"
    tiny.write_bytes(b"x")
    assert not bk.verify_file(tiny)["ok"]
    foreign = tmp_path / "other.db"
    con = sqlite3.connect(foreign)
    con.execute("create table t(a)")
    con.executemany("insert into t values (?)", [(i,) for i in range(2000)])
    con.commit()
    con.close()
    f = bk.verify_file(foreign)
    assert not f["ok"] and "missing tables" in " ".join(f["problems"])
    tampered = _dir(client) / "greenhouse-20200101-000000-manual.db"                  # changed after its manifest was written
    shutil.copy2(p, tampered)
    tampered.with_suffix(".json").write_text(json.dumps({**man, "name": tampered.name}))
    tampered.write_bytes(tampered.read_bytes() + b"tampered")
    t = bk.verify_file(tampered)
    assert not t["ok"] and "checksum differs" in " ".join(t["problems"])


def test_names_cannot_escape_the_backup_folder(client):
    _make(client)
    for bad in ("..%2f..%2fgreenhouse.db", "../x.db", "greenhouse-..\\x.db", "other.db", "greenhouse-nope.db"):
        assert client.get(f"/api/backup/{bad}/download").status_code == 404
        assert client.delete(f"/api/backup/{bad}").status_code in (404, 405)
        assert client.post(f"/api/backup/{bad}/restore", json={"confirm": True}).status_code in (404, 405)
    assert bk.path_of(client.app.state.settings, "../greenhouse-x.db") is None


def test_download_is_a_valid_gzipped_database(client, tmp_path):
    man = _make(client)
    r = client.get(f"/api/backup/{man['name']}/download")
    assert r.status_code == 200 and r.headers["content-type"] == "application/gzip"
    out = tmp_path / "dl.db"
    out.write_bytes(gzip.decompress(r.content))
    assert bk.verify_file(out)["ok"]
    assert client.get(f"/api/backup/{man['name']}/download", params={"gz": False}).content[:15] == b"SQLite format 3"


def test_restore_round_trip_replaces_everything_and_keeps_a_safety_copy(client):
    _cfg(client, name="Before backup")
    client.post("/api/maintenance", json={"title": "Task before", "interval_days": 30})
    man = _make(client)
    _cfg(client, name="After backup")
    client.post("/api/sensors", json={"id": "extra_t", "name": "x", "kind": "temperature", "zone": "soil", "unit": "C", "driver": "ds18b20",
                                      "address": {"device_id": "28-0123456789ab"}})
    client.post("/api/maintenance", json={"title": "Task after", "interval_days": 30})
    assert client.post(f"/api/backup/{man['name']}/restore", json={}).status_code == 422                # needs confirm
    r = client.post(f"/api/backup/{man['name']}/restore", json={"confirm": True})
    assert r.status_code == 200, r.text
    assert client.get("/api/config").json()["name"] == "Before backup"
    assert "extra_t" not in {s["id"] for s in client.get("/api/sensors").json()}
    titles = {t["title"] for t in client.get("/api/maintenance").json()["tasks"]}
    assert titles == {"Task before"}
    pre = r.json()["pre_restore_backup"]
    assert pre.endswith("-pre-restore.db") and (_dir(client) / pre).is_file()
    # the safety copy holds the state from just before the restore, so the restore itself can be undone
    assert client.post(f"/api/backup/{pre}/restore", json={"confirm": True}).status_code == 200
    assert client.get("/api/config").json()["name"] == "After backup" and "extra_t" in {s["id"] for s in client.get("/api/sensors").json()}
    assert client.app.state.db.integrity_check() == "ok"


def test_restore_switches_outputs_off_and_drops_running_jobs(client):
    eng, plant = client.app.state.engine, client.app.state.ctx.plant
    eng.clock = lambda: 1_800_000_000.0
    eng.reload()
    from app.services.ingest import LatestValue
    for sid, v in (("sim_tank_level", 80.0), ("sim_tank_float", 1.0), ("sim_flow_main", 0.0)):
        client.app.state.ingest.latest[sid] = LatestValue(v, 1_800_000_000, v)
    ok, msg = asyncio.run(eng.start_zone("soil_a", 60, "manual", 1_800_000_000.0))
    assert ok, msg
    assert plant.states["sim_valve_a"] is True and "soil_a" in eng.jobs
    man = _make(client)
    assert client.post(f"/api/backup/{man['name']}/restore", json={"confirm": True}).status_code == 200
    assert not plant.states["sim_valve_a"] and not plant.states.get("sim_pump") and not eng.jobs and not eng.holds
    assert eng.cfg.zones and client.get("/api/irrigation/status").status_code == 200


def test_failed_restore_leaves_live_data_untouched(client, tmp_path):
    _cfg(client, name="Live data")
    man = _make(client)
    p = _dir(client) / man["name"]
    p.write_bytes(p.read_bytes()[:5000])                                                                # truncated
    r = client.post(f"/api/backup/{man['name']}/restore", json={"confirm": True})
    assert r.status_code == 422 and "refused" in r.json()["detail"]
    assert client.get("/api/config").json()["name"] == "Live data"
    assert not [m for m in bk.list_backups(client.app.state.settings) if m["label"] == "pre-restore"]   # nothing happened at all
    assert client.post("/api/backup/greenhouse-20990101-000000-manual.db/restore", json={"confirm": True}).status_code == 404


def test_restore_from_uploaded_file(client, tmp_path):
    _cfg(client, name="Uploaded state")
    man = _make(client)
    raw = (_dir(client) / man["name"]).read_bytes()
    _cfg(client, name="Changed")
    h = {"X-Requested-With": "gcc"}
    assert client.post("/api/backup/restore-upload", content=raw, headers=h).status_code == 422          # confirm missing
    assert client.post("/api/backup/restore-upload?confirm=true", content=b"garbage" * 1000, headers=h).status_code == 422
    assert client.post("/api/backup/restore-upload?confirm=true", content=b"\x1f\x8bnot-gzip", headers=h).status_code == 422
    assert client.get("/api/config").json()["name"] == "Changed"
    assert client.post("/api/backup/restore-upload?confirm=true", content=gzip.compress(raw), headers=h).status_code == 200
    assert client.get("/api/config").json()["name"] == "Uploaded state"


def test_retention_prunes_per_label(client):
    s = client.app.state.settings
    for i in range(5):
        bk.create(client.app.state.db, s, "auto", now=1_700_000_000 + i * 86400)
    bk.create(client.app.state.db, s, "manual", now=1_700_500_000)
    for i in range(7):
        bk.create(client.app.state.db, s, "pre-restore", now=1_701_000_000 + i * 60)
    removed = bk.prune(s, keep=3)
    labels = [m["label"] for m in bk.list_backups(s)]
    assert labels.count("auto") == 3 and labels.count("manual") == 1 and labels.count("pre-restore") == 5 and len(removed) == 4
    assert not list(_dir(client).glob("*-auto.json")) or len(list(_dir(client).glob("*-auto.json"))) == 3     # manifests go with files


def test_scheduled_backup_runs_once_a_day_at_the_set_time(client):
    app = client.app
    local = lambda h, m, d=2: time.mktime((2026, 2, d, h, m, 0, 0, 0, -1))  # noqa: E731
    assert bk.run_scheduled(app, local(2, 59)) is None                         # before 03:00
    first = bk.run_scheduled(app, local(3, 5))
    assert first and first["label"] == "auto"
    assert bk.run_scheduled(app, local(9, 0)) is None                          # already done today
    assert bk.run_scheduled(app, local(3, 5, d=3))["label"] == "auto"           # next day
    client.put("/api/backup/settings", json={"enabled": False, "time": "03:00", "keep": 14})
    assert bk.run_scheduled(app, local(3, 5, d=9)) is None


def test_failed_backup_raises_an_alert_and_recovery_clears_it(client, monkeypatch):
    app = client.app
    now = time.mktime((2026, 3, 2, 4, 0, 0, 0, 0, -1))
    real = bk.create
    monkeypatch.setattr(bk, "create", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    assert bk.run_scheduled(app, now) is None
    a = [x for x in client.get("/api/alerts").json() if x["code"] == "backup_failed"]
    assert a and a[0]["severity"] == "critical" and "disk full" in a[0]["message"]
    monkeypatch.setattr(bk, "create", real)
    assert bk.run_scheduled(app, now + 60)
    assert not [x for x in client.get("/api/alerts").json() if x["code"] == "backup_failed"]


def test_copy_to_another_folder(client, tmp_path):
    usb = tmp_path / "usb"
    usb.mkdir()
    assert client.put("/api/backup/settings", json={"enabled": True, "time": "03:00", "keep": 5, "copy_dir": str(tmp_path / "nope")}).status_code == 422
    assert client.put("/api/backup/settings", json={"enabled": True, "time": "03:00", "keep": 5, "copy_dir": str(usb)}).status_code == 200
    man = _make(client)
    assert man["copy_error"] is None and (usb / man["name"]).is_file() and (usb / (man["name"][:-3] + ".json")).is_file()
    assert bk.verify_file(usb / man["name"])["ok"]
    shutil.rmtree(usb)                                                          # the USB stick is gone
    man2 = _make(client)
    assert man2["copy_error"]
    tm = time.localtime(time.time() + 2 * 86400)
    bk.run_scheduled(client.app, time.mktime((tm.tm_year, tm.tm_mon, tm.tm_mday, 4, 0, 0, 0, 0, -1)))
    assert any(a["code"] == "backup_failed" and a["subject"] == "copy" for a in client.get("/api/alerts").json())


def test_roundtrip_verification_is_clean_and_is_a_commissioning_check(client):
    r = client.post("/api/backup/verify").json()
    assert r["ok"] and r["problems"] == [] and "read back" in r["detail"]
    assert not [m for m in bk.list_backups(client.app.state.settings) if m["label"] == "verify"]       # temporary files removed
    assert not list(_dir(client).glob("verify-*"))
    c = client.post("/api/safety/checks/backup_restore/run").json()
    assert c["ok"]
    chk = next(x for x in client.get("/api/safety").json()["checks"] if x["id"] == "backup_restore")
    assert chk["has_auto"] and not chk["manual_required"] and chk["auto"]["ok"]


def test_health_reports_backup_state(client):
    def comp():
        return {c["name"]: c for c in client.get("/api/diagnostics/health").json()["components"]}["Backups"]
    assert comp()["status"] == "warn" and "no backup yet" in comp()["detail"]
    man = _make(client)
    assert comp()["status"] == "ok" and "not copied off this computer" in comp()["detail"]
    mp = _dir(client) / (man["name"][:-3] + ".json")
    d = json.loads(mp.read_text())
    d["created_ts"] -= 4 * 86400
    mp.write_text(json.dumps(d))
    assert comp()["status"] == "warn" and "h ago" in comp()["detail"]
    client.put("/api/backup/settings", json={"enabled": False, "time": "03:00", "keep": 14})
    assert "switched off" in comp()["detail"]


def test_restore_keeps_working_with_data_written_during_restore(client):
    with client.app.state.db.session() as s:
        s.add_all(Measurement(sensor_id="gh_temp_1", ts=1_700_000_000 + i, value=20.0) for i in range(500))
    man = _make(client)
    with client.app.state.db.session() as s:
        s.add(Measurement(sensor_id="gh_temp_1", ts=1_800_000_000, value=99.0))
    assert client.post(f"/api/backup/{man['name']}/restore", json={"confirm": True}).status_code == 200
    with client.app.state.db.session() as s:
        vals = [m.value for m in s.scalars(select(Measurement).where(Measurement.sensor_id == "gh_temp_1"))]
    assert len(vals) == 500 and 99.0 not in vals


def test_restore_does_not_roll_back_the_audit_trail(tmp_path):
    from fastapi.testclient import TestClient

    from app.core.settings import Settings
    from app.main import create_app
    from app.services import auth
    s = Settings(data_dir=tmp_path, autostart_ingest=False, autostart_engine=False, serve_frontend=False, auth_required=True)
    H = {"X-Requested-With": "gcc"}
    with TestClient(create_app(s)) as c:
        code = auth.setup_code_path(tmp_path).read_text().strip()
        assert c.post("/api/auth/setup", headers=H, json={"code": code, "username": "boss1", "password": "correct-horse-battery"}).status_code == 200
        man = c.post("/api/backup", headers=H).json()
        c.post("/api/maintenance", headers=H, json={"title": "After the backup", "interval_days": 9})   # audited, not in the backup
        assert c.post(f"/api/backup/{man['name']}/restore", headers=H, json={"confirm": True}).status_code == 200
        assert c.get("/api/maintenance").json()["tasks"] == []                                          # data rolled back
        paths = [(r["method"], r["path"]) for r in c.get("/api/audit").json()]
        assert ("POST", "/api/maintenance") in paths and ("POST", "/api/backup") in paths              # but the trail survived
        assert any(p[1].endswith("/restore") for p in paths)
