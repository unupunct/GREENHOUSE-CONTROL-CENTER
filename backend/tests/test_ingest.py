import asyncio
import time

from sqlalchemy import func, select

from app.core.models import Alert, Measurement, Sensor
from app.hal import DriverError


def _ingest(client):
    return client.app.state.ingest


def test_sensors_seeded_and_simulated(client):
    sensors = client.get("/api/sensors").json()
    assert len(sensors) >= 10
    assert all(s["simulated"] for s in sensors)


def test_poll_flush_writes_averaged_rows(client):
    ing = _ingest(client)
    now = time.time()
    for i in range(5):
        asyncio.run(ing.poll_once(now + i))
    n_sensors = len(client.get("/api/sensors").json())
    assert ing.flush(now + 5) == n_sensors
    with client.app.state.db.session() as s:
        assert s.scalar(select(func.count()).select_from(Measurement)) == n_sensors  # 1 row each, not 5
    # buffer emptied
    assert ing.flush() == 0


def test_history_and_vpd(client):
    ing = _ingest(client)
    now = time.time()
    asyncio.run(ing.poll_once(now))
    ing.flush(now - 60)
    h = client.get("/api/readings/history", params={"sensor_id": "gh_temp_1", "hours": 1}).json()
    assert len(h["points"]) == 1
    assert client.get("/api/readings/history", params={"sensor_id": "nope"}).status_code == 404
    v = client.get("/api/climate/vpd").json()
    assert v["available"] and 0 <= v["vpd_kpa"] < 6
    assert client.get("/api/climate/vpd/history", params={"hours": 1}).json()["points"]


def test_retention_prunes_old_rows(client):
    ing = _ingest(client)
    now = time.time()
    asyncio.run(ing.poll_once(now))
    ing.flush(now - 200 * 86400)
    ing.flush(now)  # empty buffer: no-op
    assert ing.prune(now) > 0


def test_sensor_fault_raises_single_alert_and_recovers(client, monkeypatch):
    ing = _ingest(client)
    from app.hal.simulated import SimulatedDriver
    real = SimulatedDriver.read

    async def flaky(self, spec, now):
        if spec.id == "gh_co2_1":
            raise DriverError("timeout")
        return await real(self, spec, now)

    monkeypatch.setattr(SimulatedDriver, "read", flaky)
    asyncio.run(ing.poll_once())
    asyncio.run(ing.poll_once())
    alerts = client.get("/api/alerts").json()
    assert [a["subject"] for a in alerts] == ["gh_co2_1"]
    monkeypatch.setattr(SimulatedDriver, "read", real)
    asyncio.run(ing.poll_once())
    assert client.get("/api/alerts").json() == []
    assert any(e["message"].endswith("recovered") for e in client.get("/api/events").json())


def test_out_of_range_value_is_rejected(client, monkeypatch):
    from app.hal.simulated import SimulatedDriver

    async def absurd(self, spec, now):
        return 9999.0

    monkeypatch.setattr(SimulatedDriver, "read", absurd)
    asyncio.run(_ingest(client).poll_once())
    assert _ingest(client).latest == {}
    with client.app.state.db.session() as s:
        assert s.scalar(select(func.count()).select_from(Alert)) > 0
        assert s.scalar(select(func.count()).select_from(Sensor)) > 0
