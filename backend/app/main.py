"""FastAPI application factory and lifecycle wiring."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.routes import documents, health, send_jobs, whatsapp
from app.api.routes import settings as settings_routes
from app.config import Settings
from app.db import Database
from app.domains.documents.scanner import DocumentScanner
from app.domains.documents.service import DocumentService
from app.domains.send_jobs.repository import SendJobRepository
from app.domains.send_jobs.service import SendJobService, SendJobWorker
from app.domains.settings.service import WorkspaceSettingsService
from app.integrations.whatsapp.client import HttpWhatsAppBridge, WhatsAppBridge
from app.integrations.whatsapp.readiness import BridgeReadiness


class RuntimeCORSMiddleware:
    """Read CORS configuration after lifespan has loaded runtime settings."""

    def __init__(self, app: ASGIApp, application: FastAPI) -> None:
        self.app = app
        self.application = application

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        middleware = CORSMiddleware(
            self.app, allow_origins=self.application.state.settings.cors_origin_list,
            allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
        )
        await middleware(scope, receive, send)


def create_app(
    settings: Settings | None = None,
    bridge: WhatsAppBridge | None = None,
    *,
    start_worker: bool = True,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        runtime_settings = settings if settings is not None else Settings()
        database = Database(runtime_settings.database_path)
        database.initialize()
        workspace_settings = WorkspaceSettingsService(
            database,
            {
                category: runtime_settings.roots_for(category)
                for category in ("bills", "credit_notes", "debit_notes")
            },
        )
        document_service = DocumentService(DocumentScanner(workspace_settings.root_paths()))
        repository = SendJobRepository(database)
        runtime_bridge = bridge if bridge is not None else HttpWhatsAppBridge(
            runtime_settings.whatsapp_bridge_url,
            runtime_settings.bridge_timeout_seconds,
            runtime_settings.whatsapp_bridge_api_key,
        )
        readiness = BridgeReadiness(
            runtime_bridge,
            lambda: [
                str(path) for paths in workspace_settings.root_paths().values() for path in paths
            ],
        )
        send_job_service = SendJobService(repository, document_service, runtime_bridge, readiness)
        worker = SendJobWorker(send_job_service, runtime_settings.worker_poll_seconds)
        application.state.settings = runtime_settings
        application.state.database = database
        application.state.workspace_settings = workspace_settings
        application.state.document_service = document_service
        application.state.bridge = runtime_bridge
        application.state.bridge_readiness = readiness
        application.state.send_job_service = send_job_service
        application.state.worker = worker
        try:
            if start_worker:
                await worker.start()
            else:
                repository.recover_incomplete()
            yield
        finally:
            try:
                if start_worker:
                    await worker.stop()
            finally:
                close = getattr(runtime_bridge, "close", None)
                if close is not None:
                    result = close()
                    if inspect.isawaitable(result):
                        await result

    application = FastAPI(title="Office Document Dashboard API", lifespan=lifespan)
    application.add_middleware(RuntimeCORSMiddleware, application=application)
    application.include_router(health.router, prefix="/api")
    application.include_router(documents.router, prefix="/api")
    application.include_router(send_jobs.router, prefix="/api")
    application.include_router(settings_routes.router, prefix="/api")
    application.include_router(whatsapp.router, prefix="/api")
    return application


app = create_app()
