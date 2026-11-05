"""Separate mobile-only gateway. Never include office administration routes here."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings
from app.db import Database
from app.domains.documents.scanner import DocumentScanner
from app.domains.mobile.invoices import InvoiceCatalogue, invoice_filename
from app.domains.mobile.office_routes import install_office_routes
from app.domains.mobile.reports import statement_filename
from app.domains.mobile.service import MobileService
from app.domains.mobile.store import MobileStore
from app.domains.settings.service import WorkspaceSettingsService


def build_mobile(settings: Settings) -> MobileService:
    database = Database(settings.database_path)
    database.initialize()
    workspace = WorkspaceSettingsService(
        database,
        {
            category: settings.roots_for(category)
            for category in ("bills", "credit_notes", "debit_notes")
        },
    )

    def roots_provider() -> list[Path]:
        roots = list(workspace.root_paths().get("bills", ()))
        roots.extend(
            Path(value.strip())
            for value in settings.mobile_archive_roots.split("|")
            if value.strip()
        )
        return roots

    scanner = DocumentScanner(
        {"bills": roots_provider()}, ignored_directory_names=settings.ignored_directory_names
    )
    return MobileService(settings, MobileStore(database), InvoiceCatalogue(scanner, roots_provider))


security = HTTPBearer(auto_error=False)


def instance(request: Request) -> MobileService:
    return request.app.state.mobile  # type: ignore[no-any-return]


def user(
    request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)]
) -> dict[str, Any]:
    result = instance(request).store.authenticate(credentials.credentials) if credentials else None
    if result is None:
        raise HTTPException(401, "Access expired or was revoked. Ask the office for a new invite.")
    return result


CurrentUser = Annotated[dict[str, Any], Depends(user)]


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PairRequest(Payload):
    invite_code: str = Field(min_length=30, max_length=100)
    phone: str | None = Field(default=None, pattern=r"^[1-9][0-9]{7,14}$")


class ReportRequest(Payload):
    party_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    as_of: date
    request_key: str = Field(min_length=8, max_length=100, pattern=r"^[a-zA-Z0-9-]+$")


def create_mobile_app(
    settings: Settings | None = None,
    service: MobileService | None = None,
    apk_path: Path | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.mobile = service or build_mobile(settings or Settings())
        app.state.mobile.store.recover()
        app.state.mobile.cleanup_reports()
        try:
            yield
        finally:
            app.state.mobile.close()

    app = FastAPI(
        title="Office mobile reports",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    attempts: dict[str, deque[float]] = defaultdict(deque)

    @app.middleware("http")
    async def protect(request: Request, call_next: Any) -> Any:
        from starlette.responses import JSONResponse

        # Native app uses no Origin header. This service has no browser-based login.
        if request.headers.get("origin"):
            return JSONResponse({"detail": "Browser requests are not allowed."}, status_code=403)
        host = request.client.host if request.client else "unknown"
        bucket = host + (":pair" if request.url.path == "/mobile/v1/pair" else ":api")
        current = time.monotonic()
        queue = attempts[bucket]
        while queue and queue[0] < current - 60:
            queue.popleft()
        if len(queue) >= (10 if bucket.endswith(":pair") else 180):
            return JSONResponse(
                {"detail": "Too many requests. Wait a minute and try again."}, status_code=429
            )
        queue.append(current)
        # Bound storage independently of client-controlled forwarded headers.
        if len(attempts) > 2000:
            for key in list(attempts):
                if not attempts[key] or attempts[key][-1] < current - 60:
                    del attempts[key]
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"service": "office-mobile", "manual_only": True}

    @app.get("/install/android.apk")
    def android_app() -> FileResponse:
        # The APK contains app code and the office URL, never sessions or private keys.
        # Allow initial installation before pairing, inside the private VPN only.
        path = apk_path or (
            Path(__file__).resolve().parents[2] / "output" / "android" / "HS-Traders-Office.apk"
        )
        if not path.is_file():
            raise HTTPException(404, "The Android installer is not available yet.")
        return FileResponse(
            path,
            media_type="application/vnd.android.package-archive",
            filename="HS-Traders-Office.apk",
        )

    @app.post("/mobile/v1/pair")
    def pair(payload: PairRequest, request: Request) -> dict[str, str]:
        try:
            result = instance(request).store.pair(payload.invite_code, payload.phone)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if result is None:
            raise HTTPException(401, "Invite expired or already used. Ask for a new invite.")
        return result

    @app.get("/mobile/v1/me")
    def me(current: CurrentUser) -> dict[str, Any]:
        return {"id": current["id"], "name": current["name"], "phone": current["phone"]}

    @app.post("/mobile/v1/logout")
    def logout(
        request: Request,
        current: CurrentUser,
        credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    ) -> dict[str, bool]:
        instance(request).store.logout(credentials.credentials)
        return {"ok": True}

    @app.get("/mobile/v1/parties")
    def parties(
        request: Request, current: CurrentUser, q: str = Query(default="", max_length=100)
    ) -> list[dict[str, str]]:
        return instance(request).store.parties(q)

    @app.post("/mobile/v1/reports", status_code=202)
    def report(payload: ReportRequest, request: Request, current: CurrentUser) -> dict[str, Any]:
        try:
            return instance(request).submit(
                current["id"], payload.party_id, payload.as_of, payload.request_key
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/mobile/v1/reports")
    def history(request: Request, current: CurrentUser) -> list[dict[str, Any]]:
        instance(request).cleanup_reports()
        return instance(request).store.jobs(current["id"])

    @app.get("/mobile/v1/reports/{job_id}")
    def get_report(job_id: str, request: Request, current: CurrentUser) -> dict[str, Any]:
        row = instance(request).store.job(job_id, current["id"])
        if row is None:
            raise HTTPException(404, "Report not found.")
        return instance(request).store.public(row)

    @app.get("/mobile/v1/reports/{job_id}/pdf")
    def report_pdf(job_id: str, request: Request, current: CurrentUser) -> FileResponse:
        try:
            path, row = instance(request).report_file(current["id"], job_id)
            return FileResponse(
                path, media_type="application/pdf", filename=statement_filename(row["party_name"])
            )
        except (ValueError, OSError) as exc:
            raise HTTPException(
                404, "Report unavailable or expired. Request a fresh statement."
            ) from exc

    @app.get("/mobile/v1/financial-years")
    def years(request: Request, current: CurrentUser) -> dict[str, Any]:
        values = instance(request).catalogue.years()
        return {"years": values, "default": values[0] if values else None}

    @app.get("/mobile/v1/invoices")
    def invoices(
        request: Request,
        current: CurrentUser,
        year: str = Query(pattern=r"^\d{2}-\d{2}$"),
        bill: str = Query(min_length=1, max_length=80),
    ) -> list[dict[str, Any]]:
        try:
            return instance(request).catalogue.search(year, bill)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/mobile/v1/invoices/{file_id}/pdf")
    def invoice_pdf(file_id: str, request: Request, current: CurrentUser) -> FileResponse:
        try:
            path, row = instance(request).catalogue.file(file_id)
            return FileResponse(path, media_type="application/pdf", filename=invoice_filename(row))
        except OSError as exc:
            raise HTTPException(
                404, "The saved bill PDF is unavailable. Ask the office to check it."
            ) from exc
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/mobile/v1/{kind}/{file_id}/send-to-me")
    async def send(
        kind: str, file_id: str, request: Request, current: CurrentUser
    ) -> dict[str, Any]:
        if kind not in {"reports", "invoices"}:
            raise HTTPException(404, "Unknown document type.")
        try:
            return await instance(request).send(
                current, "report" if kind == "reports" else "invoice", file_id
            )
        except OSError as exc:
            raise HTTPException(
                404, "The document file is unavailable. Ask the office to check it."
            ) from exc
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    install_office_routes(app, user)
    return app


app = create_mobile_app()
