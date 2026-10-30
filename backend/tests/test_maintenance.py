import time

from sqlalchemy import select

from app.core.models import MaintenanceTask
from app.services import maintenance as m

DAY = 86400


def _task(client, **kw):
    body = {"title": "Clean the filter", "category": "filter", "interval_days": 10, **kw}
    r = client.post("/api/maintenance", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _age(client, tid, days):
    with client.app.state.db.session() as s:
        s.get(MaintenanceTask, tid).created_at = int(time.time() - days * DAY)


def test_status_transitions_and_alerts(client):
    tid = _task(client)
    assert client.get("/api/maintenance").json()["tasks"][0]["status"] == "ok"
    _age(client, tid, 9)                                   # within 20% of the interval: due soon
    t = client.get("/api/maintenance").json()
    assert t["tasks"][0]["status"] == "due_soon" and t["due_soon"] == 1
    _age(client, tid, 11)
    t = client.get("/api/maintenance").json()
    assert t["tasks"][0]["status"] == "overdue" and t["overdue"] == 1
    assert client.post("/api/maintenance/check").json() == {"overdue": 1, "tasks": 1}
    assert [a["code"] for a in client.get("/api/alerts").json()] == ["maintenance_due"]
    assert client.post("/api/maintenance/check").json()["overdue"] == 1
    assert len(client.get("/api/alerts").json()) == 1       # no duplicate alert
    assert client.post(f"/api/maintenance/{tid}/done", json={"note": "cleaned the disc filter"}).status_code == 200
    assert client.get("/api/alerts").json() == []
    t = client.get("/api/maintenance").json()["tasks"][0]
    assert t["status"] == "ok" and t["last_done_ts"] is not None
    assert client.get(f"/api/maintenance/{tid}/log").json()[0]["note"] == "cleaned the disc filter"
    assert client.post("/api/maintenance/nope/done", json={}).status_code == 404


def test_pure_status_boundaries():
    now = 1_000_000.0
    t = MaintenanceTask(id="x", title="x", category="other", interval_days=100, created_at=int(now - 79 * DAY), enabled=True, notes="")
    assert m.status_of(t, now)["status"] == "ok"
    t.created_at = int(now - 81 * DAY)
    assert m.status_of(t, now)["status"] == "ok"            # due in 19 days; the warning window is min(7 d, 20 %) = 7 days
    t.created_at = int(now - 94 * DAY)
    assert m.status_of(t, now)["status"] == "due_soon"
    t.created_at = int(now - 101 * DAY)
    assert m.status_of(t, now)["status"] == "overdue"
    t.last_done_ts = int(now - DAY)
    assert m.status_of(t, now)["status"] == "ok"            # completion resets the clock
    t.enabled = False
    assert m.status_of(t, now)["status"] == "disabled"


def test_validation(client):
    assert client.post("/api/maintenance", json={"title": "x", "interval_days": 5}).status_code == 422          # title too short
    assert client.post("/api/maintenance", json={"title": "Check it", "interval_days": 0}).status_code == 422
    assert client.post("/api/maintenance", json={"title": "Check it", "interval_days": 99999}).status_code == 422
    assert client.post("/api/maintenance", json={"title": "Check it", "interval_days": 5, "subject_kind": "sensor", "subject_id": "ghost"}).status_code == 422
    assert client.post("/api/maintenance", json={"title": "Check it", "interval_days": 5, "category": "magic"}).status_code == 422
    tid = _task(client, subject_kind="sensor", subject_id="gh_temp_1")
    assert client.post("/api/maintenance", json={"title": "Clean the filter", "interval_days": 5, "subject_kind": "sensor", "subject_id": "gh_temp_1"}).status_code == 409
    assert client.put(f"/api/maintenance/{tid}", json={"title": "Clean the filter", "interval_days": 30, "category": "filter", "subject_kind": "sensor", "subject_id": "gh_temp_1"}).status_code == 200
    assert client.get("/api/maintenance").json()["tasks"][0]["interval_days"] == 30
    assert client.delete(f"/api/maintenance/{tid}").status_code == 200 and client.delete(f"/api/maintenance/{tid}").status_code == 404


def test_suggestions_come_from_real_equipment_only(client):
    base = client.get("/api/maintenance/suggestions/list").json()["suggestions"]
    assert all(s["subject_kind"] == "system" for s in base)                       # only simulated gear: no sensor/pump tasks
    assert not any("pH" in s["title"] for s in base)
    client.put("/api/hardware/buses", json=[{"id": "rs485_1", "port": "COM9"}])
    client.post("/api/sensors", json={"id": "ph_main", "name": "Main pH", "kind": "ph", "zone": "hydroponic", "unit": "pH", "driver": "modbus_rtu",
                                      "address": {"bus": "rs485_1", "slave": 5, "register": 0}})
    client.post("/api/actuators", json={"id": "real_pump", "name": "Main pump", "kind": "pump", "driver": "gpio_output", "max_runtime_s": 600, "address": {"pin": 17}})
    sug = {s["title"]: s for s in client.get("/api/maintenance/suggestions/list").json()["suggestions"]}
    ph = next(s for t, s in sug.items() if "pH probe" in t)
    assert ph["interval_days"] == 30 and ph["subject_id"] == "ph_main" and "starting suggestion" in ph["basis"]
    assert any("pump" in t.lower() for t in sug) and "Clean irrigation filter" in sug and "Test the hardware emergency stop" in sug
    made = client.post("/api/maintenance/suggestions/apply", json={"ids": [ph["id"]]}).json()["created"]
    assert made == [ph["id"]]
    assert client.post("/api/maintenance/suggestions/apply", json={"ids": [ph["id"]]}).json()["created"] == []   # idempotent
    allmade = client.post("/api/maintenance/suggestions/apply", json={}).json()["created"]
    assert ph["id"] not in allmade and len(allmade) >= 3
    assert next(s for s in client.get("/api/maintenance/suggestions/list").json()["suggestions"] if s["id"] == ph["id"])["exists"]


def test_replacement_history(client):
    r = client.post("/api/maintenance/replacements", json={"subject_kind": "sensor", "subject_id": "ph_main", "reason": "drifting",
                                                           "old_item": "pH probe A", "new_item": "pH probe B", "ts": 1_700_000_000})
    assert r.status_code == 201
    client.post("/api/maintenance/replacements", json={"subject_kind": "actuator", "subject_id": "pump1", "reason": "seal worn"})
    allr = client.get("/api/maintenance/replacements/list").json()
    assert len(allr) == 2 and allr[0]["subject_id"] == "pump1"                        # newest first
    one = client.get("/api/maintenance/replacements/list", params={"subject_id": "ph_main"}).json()
    assert len(one) == 1 and one[0]["old_item"] == "pH probe A" and one[0]["ts"] == 1_700_000_000
    assert client.delete(f"/api/maintenance/replacements/{one[0]['id']}").status_code == 200
    assert client.delete("/api/maintenance/replacements/9999").status_code == 404
    assert client.post("/api/maintenance/replacements", json={"subject_kind": "sensor", "subject_id": ""}).status_code == 422
    with client.app.state.db.session() as s:
        assert s.scalars(select(MaintenanceTask)).first() is None


def test_old_logs_are_pruned_but_active_alerts_and_recent_rows_stay(client):
    from sqlalchemy import select as sel

    from app.core.models import Alert, AuditLog, Event
    from app.services import events
    now = int(time.time())
    old = now - 400 * DAY
    with client.app.state.db.session() as s:
        s.add_all([Event(ts=old, level="info", source="t", message="old"), Event(ts=now, level="info", source="t", message="new")])
        s.add_all([AuditLog(ts=old, method="POST", path="/x", status=200), AuditLog(ts=now, method="POST", path="/y", status=200)])
        s.add_all([Alert(ts=old, severity="warning", code="a", subject="1", message="resolved old", active=False),
                   Alert(ts=old, severity="warning", code="b", subject="2", message="still active", active=True)])
    r = events.prune(client.app.state.db, 365)
    assert r["events"] >= 1 and r["audit"] == 1 and r["alerts"] == 1
    with client.app.state.db.session() as s:
        assert [e.message for e in s.scalars(sel(Event)) if e.message in ("old", "new")] == ["new"]
        assert [a.message for a in s.scalars(sel(Alert)) if a.code in ("a", "b")] == ["still active"]
        assert [a.path for a in s.scalars(sel(AuditLog))] == ["/y"]
