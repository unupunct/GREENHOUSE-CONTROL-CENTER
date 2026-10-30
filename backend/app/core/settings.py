"""Process-level settings (environment variables, prefix ``GCC_``).

These are deployment settings. Greenhouse configuration (dimensions, crops,
...) lives in the database and is edited through the API/UI.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GCC_", env_file=".env", extra="ignore")

    data_dir: Path = PROJECT_ROOT / "data"
    frontend_dist: Path = PROJECT_ROOT / "frontend" / "dist"

    # Demo mode: seeds simulated sensors and equipment on an empty database. Set false on a real installation.
    simulate: bool = True

    # Sampling is kept in memory; only averaged samples are written to disk
    # so the microSD card is not worn out by per-second writes.
    poll_interval_s: float = 5.0
    flush_interval_s: float = 60.0
    retention_days: int = 90

    autostart_ingest: bool = True
    autostart_engine: bool = True
    serve_frontend: bool = True

    # Security. Turning authentication off is for an isolated development machine only.
    auth_required: bool = True
    session_idle_hours: float = 12.0
    session_max_days: float = 7.0
    cookie_secure: bool | None = None  # None: Secure when the request arrived over https
    max_body_mb: float = 2.0
    max_upload_mb: float = 200.0       # backup restore uploads

    rollup_retention_days: int = 1095  # hourly roll-ups outlive raw samples
    api_docs: bool = False             # /docs and /openapi.json (off: smaller attack surface)
    log_retention_days: int = 365      # events, audit log, resolved alerts

    @property
    def db_path(self) -> Path:
        return self.data_dir / "greenhouse.db"
