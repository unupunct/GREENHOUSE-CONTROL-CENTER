"""Regression net: every parameter-free GET endpoint answers without a server error."""

import pytest


def _gets(app):
    out = []
    for path, ops in app.openapi()["paths"].items():
        op = ops.get("get")
        if op is None or "{" in path:
            continue
        required = [p for p in op.get("parameters", []) if p.get("required")]
        if not required:
            out.append(path)
    return sorted(out)


def test_inventory_is_not_trivial(client):
    assert len(_gets(client.app)) > 40


def test_all_parameter_free_gets_succeed(client):
    bad = {}
    for path in _gets(client.app):
        r = client.get(path)
        if r.status_code != 200:
            bad[path] = r.status_code
    assert bad == {}


@pytest.mark.parametrize("path", ["/api/readings/history?sensor_id=gh_temp_1", "/api/analytics/export/measurements.csv?sensor_id=gh_temp_1",
                                  "/api/plants/tomato", "/api/encyclopedia/rpi5", "/api/planner/plan", "/api/shopping/export.pdf",
                                  "/api/manual/download.pdf", "/api/layout/export.pdf", "/api/analytics/report.pdf", "/api/backup"])
def test_representative_parameterised_gets(client, path):
    assert client.get(path).status_code == 200


def test_openapi_documents_every_router(client):
    paths = " ".join(client.app.openapi()["paths"])
    for prefix in ("/api/auth", "/api/backup", "/api/diagnostics", "/api/wizard", "/api/manual", "/api/encyclopedia", "/api/analytics",
                   "/api/layout", "/api/climate", "/api/irrigation", "/api/planner", "/api/maintenance", "/api/hardware"):
        assert prefix in paths, prefix
