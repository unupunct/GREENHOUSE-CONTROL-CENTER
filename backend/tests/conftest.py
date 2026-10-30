import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.settings import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, autostart_ingest=False, autostart_engine=False, serve_frontend=False,
                    auth_required=False, poll_interval_s=1, flush_interval_s=1)


@pytest.fixture
def client(settings):
    app = create_app(settings)
    with TestClient(app) as c:
        yield c
