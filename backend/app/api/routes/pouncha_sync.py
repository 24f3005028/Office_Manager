"""Pouncha daily sync status, manual run and Excel upload endpoints."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Annotated, cast

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.api.schemas import (
    PounchaSchedulerStatusResponse,
    PounchaSyncQueuedResponse,
    PounchaSyncRunRequest,
    PounchaSyncRunResponse,
    PounchaSyncStatusResponse,
)
from app.domains.pouncha_sync.models import (
    PounchaSyncRun,
    PounchaTrigger,
)
from app.domains.pouncha_sync.parser import PounchaParseError
from app.domains.pouncha_sync.scheduler import (
    PounchaSchedulerStatus,
    PounchaSyncScheduler,
)
from app.domains.pouncha_sync.service import (
    PounchaNotConfiguredError,
    PounchaSyncError,
    PounchaSyncService,
)
from app.domains.pouncha_sync.sheets_client import PounchaSheetError

router = APIRouter(prefix="/pouncha-sync", tags=["pouncha sync"])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_UPLOAD_SUFFIXES = {".xlsx", ".xlsm"}


def _service(request: Request) -> PounchaSyncService:
    service = getattr(request.app.state, "pouncha_sync_service", None)
    if service is None:
        raise HTTPException(
            status_code=503, detail="Pouncha sync is not initialized."
        )
    return cast(PounchaSyncService, service)


def _scheduler(request: Request) -> PounchaSyncScheduler | None:
    return getattr(request.app.state, "pouncha_scheduler", None)


def _run_response(run: PounchaSyncRun) -> PounchaSyncRunResponse:
    return PounchaSyncRunResponse(
        run_id=run.run_id,
        trigger_type=run.trigger_type,
        start_date=run.start_date,
        end_date=run.end_date,
        exported_sale_count=run.exported_sale_count,
        already_in_sheet_count=run.already_in_sheet_count,
        appended_count=run.appended_count,
        status=run.status,  # type: ignore[arg-type]
        error_message=run.error_message,
        warnings=list(run.warnings),
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


def _scheduler_response(
    status: PounchaSchedulerStatus | None,
) -> PounchaSchedulerStatusResponse:
    if status is None:
        return PounchaSchedulerStatusResponse(
            enabled=False,
            running=False,
            timezone="Asia/Kolkata",
            next_run_at=None,
            waiting_for_busy=False,
            last_check_at=None,
            last_success_at=None,
            last_error=None,
        )
    return PounchaSchedulerStatusResponse(
        enabled=status.enabled,
        running=status.running,
        timezone=status.timezone,
        next_run_at=status.next_run_at,
        waiting_for_busy=status.waiting_for_busy,
        last_check_at=status.last_check_at,
        last_success_at=status.last_success_at,
        last_error=status.last_error,
    )


@router.get("/status", response_model=PounchaSyncStatusResponse)
def pouncha_status(request: Request) -> PounchaSyncStatusResponse:
    service = _service(request)
    scheduler = _scheduler(request)
    service_status = service.status()
    return PounchaSyncStatusResponse(
        configured=service_status.configured,
        upload_configured=service_status.upload_configured,
        sheets_configured=service_status.sheets_configured,
        busy_configured=service_status.busy_configured,
        busy_calibrated=service_status.busy_calibrated,
        sync_enabled=service_status.sync_enabled,
        scheduler=_scheduler_response(
            scheduler.status() if scheduler is not None else None
        ),
        last_run=(
            _run_response(service_status.last_run)
            if service_status.last_run is not None
            else None
        ),
        active_run=(
            _run_response(service_status.active_run)
            if service_status.active_run is not None
            else None
        ),
        recent_runs=[
            _run_response(run) for run in service_status.recent_runs
        ],
    )


@router.post(
    "/run",
    response_model=PounchaSyncQueuedResponse,
    status_code=202,
)
async def queue_pouncha_run(
    request: Request,
    payload: PounchaSyncRunRequest | None = None,
) -> PounchaSyncQueuedResponse:
    service = _service(request)
    active = service.repository.active_run()
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "A Pouncha sync is already running. "
                f"Run id: {active.run_id}."
            ),
        )
    body = payload or PounchaSyncRunRequest()
    try:
        run = service.queue_busy_run(
            start_date=body.start_date,
            end_date=body.end_date,
            trigger_type=PounchaTrigger.MANUAL_BUSY,
        )
    except PounchaNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PounchaSyncQueuedResponse(run_id=run.run_id, status="queued")


@router.get("/runs/{run_id}", response_model=PounchaSyncRunResponse)
def pouncha_run(request: Request, run_id: str) -> PounchaSyncRunResponse:
    service = _service(request)
    run = service.repository.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Pouncha run not found.")
    return _run_response(run)


@router.post("/upload-excel", response_model=PounchaSyncRunResponse)
async def upload_pouncha_excel(
    request: Request,
    file: Annotated[UploadFile, File()],
    start_date: Annotated[date | None, Form()] = None,
    end_date: Annotated[date | None, Form()] = None,
) -> PounchaSyncRunResponse:
    service = _service(request)
    filename = file.filename or "AccountLedger_Sales.xlsx"
    suffix = ("." + filename.rsplit(".", 1)[-1].casefold()) if "." in filename else ""
    if suffix not in _UPLOAD_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail="Upload the BUSY Account Ledger as an .xlsx workbook.",
        )
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="The uploaded workbook is empty.")
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413, detail="The uploaded workbook is larger than 25 MB."
        )
    try:
        run = await asyncio.to_thread(
            service.run_upload,
            filename=filename,
            contents=contents,
            start_date=start_date,
            end_date=end_date,
        )
    except PounchaNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PounchaParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PounchaSheetError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except PounchaSyncError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _run_response(run)
