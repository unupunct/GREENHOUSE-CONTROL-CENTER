def test_health_and_database_integrity(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["database"] == "ok" and h["simulated"] is True


def test_system_info(client):
    s = client.get("/api/system").json()
    assert "checks" in s and "compatible" in s and s["disk_total_gb"] > 0


def test_safety_gate_is_closed(client):
    s = client.get("/api/safety").json()
    assert s["production_automation_allowed"] is False
    assert len(s["checks"]) == 14


def test_ack_alert(client):
    assert client.post("/api/alerts/999/ack").status_code == 404
