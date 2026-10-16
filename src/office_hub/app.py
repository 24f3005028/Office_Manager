"""FastAPI application factory and lifecycle."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import Settings, get_settings
from .database import Database
from .logging_config import configure_logging
from .scheduler import JobScheduler
from .web.routes import router
from .worker import JobWorker


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    settings.ensure_runtime_dirs()
    configure_logging(settings)

    database = Database(settings.resolved_database_url)
    database.create_schema()
    worker = JobWorker(database, settings)
    scheduler = JobScheduler(database, settings)
    app.state.db = database
    app.state.worker = worker
    app.state.scheduler = scheduler

    if settings.enable_worker:
        worker.start()
    if settings.enable_scheduler:
        scheduler.start()
    try:
        yield
    finally:
        scheduler.stop()
        worker.stop()
        database.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title=(settings or get_settings()).app_name, lifespan=lifespan)
    app.state.settings = settings or get_settings()
    static_dir = Path(__file__).parent / "web" / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.include_router(router)
    return app


app = create_app()
