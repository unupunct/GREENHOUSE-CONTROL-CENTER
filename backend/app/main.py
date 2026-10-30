from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.hardware import load_buses
from app.api.hardware import router as hardware_router
from app import security
from app.api.analytics import router as analytics_router
from app.api.auth import router as auth_router
from app.api.backup import router as backup_router
from app.api.climate import router as climate_router
from app.api.irrigation import router as irrigation_router
from app.api.diagnostics import router as diagnostics_router
from app.api.encyclopedia import router as encyclopedia_router
from app.api.knowledge import router as knowledge_router
from app.api.layout import router as layout_router
from app.api.maintenance import router as maintenance_router
from app.api.manual import router as manual_router
from app.api.planner import router as planner_router
from app.api.wizard import router as wizard_router
from app.api.routes import router
from app.core.db import Database
from app.automation.climate import ClimateEngine
from app.automation.engine import IrrigationEngine
from app.hal import DriverRegistry, HalContext
from app.hal.outputs import OutputRegistry
from app.services import auth as auth_svc
from app.services import commissioning
from app.core.settings import Settings
from app.planner.shopping import seed_offers
from app.services import events
from app.services.greenhouse_config import GreenhouseConfig, load_config, save_config
from app.services.ingest import IngestService, seed_demo_irrigation, seed_sensors


async def _housekeeping(app: FastAPI) -> None:
    """Hourly: maintenance-due alerts and host health thresholds."""
    from app.services import backup, diagnostics, maintenance
    while True:
        try:
            diagnostics.sync_health_alerts(app)
            maintenance.check_alerts(app.state.db)
            backup.run_scheduled(app)
            events.prune(app.state.db, app.state.settings.log_retention_days)
            auth_svc.purge_expired(app.state.db, app.state.settings.session_idle_hours * 3600, app.state.settings.session_max_days * 86400)
        except Exception:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).exception("housekeeping failed")
        await asyncio.sleep(3600)


def create_app(settings: Settings | None = None, ctx: HalContext | None = None) -> FastAPI:
    settings = settings or Settings()
    db = Database(settings.db_path)
    db.create_all()
    ctx = ctx or HalContext()
    ctx.buses.configure(load_buses(db))
    drivers = DriverRegistry(ctx)
    ingest = IngestService(db, settings, drivers)
    outputs = OutputRegistry(ctx)
    engine = IrrigationEngine(db, outputs, ingest, gate_fn=lambda: commissioning.gate_open(db),
                              level_fn=lambda: load_config(db).automation_level.value)

    @asynccontextmanager
    async def lifespan(app: FastAPI):

        from app.core.models import AppSetting
        with db.session() as s:
            first_run = s.get(AppSetting, "greenhouse") is None
        if first_run:
            save_config(db, GreenhouseConfig())
            events.log_event(db, "info", "system", "First run: default greenhouse config created")
        seed_offers(db)
        if settings.auth_required and auth_svc.count_users(db) == 0:
            auth_svc.ensure_setup_code(settings.data_dir)
            logging.getLogger("app.security").warning(
                "No users yet. Open the web interface and create the administrator with the setup code in %s",
                auth_svc.setup_code_path(settings.data_dir))
        if settings.simulate and seed_sensors(db):
            events.log_event(db, "info", "system", "Seeded simulated sensor registry")
        if settings.simulate:
            seed_demo_irrigation(db)  # after the sensors: seed_sensors only runs on an empty registry
        events.log_event(db, "info", "system", f"Backend {__version__} started")
        if settings.autostart_ingest:
            await ingest.poll_once()  # populate dashboard immediately
            ingest.start()
        await engine.startup()  # every output OFF, e-stop latch restored
        await climate.startup()
        housekeeping = None
        if settings.autostart_engine:
            engine.start()
            climate.start()
            housekeeping = asyncio.create_task(_housekeeping(app))
        yield
        if housekeeping:
            housekeeping.cancel()
        await climate.stop()
        await engine.stop()
        await ingest.stop()
        db.dispose()

    climate = ClimateEngine(db, outputs, ingest, estop_fn=lambda: engine.estop,
                            gate_fn=lambda: commissioning.gate_open(db),
                            level_fn=lambda: load_config(db).automation_level.value)

    limiter = auth_svc.RateLimiter()

    app = FastAPI(title="Greenhouse Control Center", version=__version__, lifespan=lifespan,
                  docs_url="/docs" if settings.api_docs else None, redoc_url=None,
                  openapi_url="/openapi.json" if settings.api_docs else None)
    app.state.settings, app.state.db, app.state.ingest = settings, db, ingest
    app.state.limiter = limiter
    app.state.ctx, app.state.drivers = ctx, drivers
    app.state.outputs, app.state.engine, app.state.climate = outputs, engine, climate
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    security.install(app)  # added last so it runs first
    app.include_router(auth_router)
    app.include_router(router)
    app.include_router(hardware_router)
    app.include_router(planner_router)
    app.include_router(irrigation_router)
    app.include_router(climate_router)
    app.include_router(knowledge_router)
    app.include_router(encyclopedia_router)
    app.include_router(maintenance_router)
    app.include_router(diagnostics_router)
    app.include_router(backup_router)
    app.include_router(wizard_router)
    app.include_router(manual_router)
    app.include_router(analytics_router)
    app.include_router(layout_router)

    dist = settings.frontend_dist
    if settings.serve_frontend and (dist / "index.html").exists():
        class _Immutable(StaticFiles):  # hashed asset names: cache for a year
            async def get_response(self, path, scope):
                r = await super().get_response(path, scope)
                r.headers["Cache-Control"] = "public, max-age=31536000, immutable"
                return r

        app.mount("/assets", _Immutable(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            f = (dist / path).resolve()
            if path and f.is_file() and dist.resolve() in f.parents:
                return FileResponse(f, headers={"Cache-Control": "no-cache"})
            return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})

    return app
