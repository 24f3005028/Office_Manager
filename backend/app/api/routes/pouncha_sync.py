"""User-triggered sync only: reads never queue work or drive BUSY."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from pydantic import BaseModel, ConfigDict

from app.domains.pouncha_sync.parser import SyncError
from app.domains.pouncha_sync.service import PounchaService


def check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin not in request.app.state.settings.cors_origin_list:
        raise HTTPException(403, "Browser origin is not allowed.")


router = APIRouter(
    prefix="/pouncha-sync", tags=["manual pouncha sync"], dependencies=[Depends(check_origin)]
)


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_date: date | None = None
    end_date: date
    preview_only: bool = False
    office_warning: bool = False


def service(request: Request) -> PounchaService:
    return request.app.state.pouncha_service  # type: ignore[no-any-return]


@router.get("/status")
def status(request: Request) -> dict[str, Any]:
    return service(request).status()


@router.post("/run", status_code=202)
def run(request: Request, payload: RunRequest, tasks: BackgroundTasks) -> dict[str, Any]:
    instance = service(request)
    try:
        result = instance.queue(payload.start_date, payload.end_date, payload.preview_only, "busy")
    except SyncError as exc:
        raise HTTPException(409, str(exc)) from exc
    tasks.add_task(instance.execute, result["run_id"], None, payload.office_warning)
    return result


@router.post("/upload", status_code=202)
async def upload(
    request: Request,
    tasks: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    end_date: Annotated[date, Form()],
    start_date: Annotated[date | None, Form()] = None,
    preview_only: Annotated[bool, Form()] = False,
) -> dict[str, Any]:
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(400, "Upload the original .xlsx Sales ledger export.")
    content = await file.read(25 * 1024 * 1024 + 1)
    await file.close()
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(413, "The workbook exceeds 25 MiB.")
    instance = service(request)
    try:
        result = instance.queue(start_date, end_date, preview_only, "upload")
    except SyncError as exc:
        raise HTTPException(409, str(exc)) from exc
    tasks.add_task(instance.execute, result["run_id"], content)
    return result


@router.get("/runs/{run_id}")
def get_run(request: Request, run_id: str) -> dict[str, Any]:
    repository = service(request).repository
    result = repository.get(run_id)
    if result is None:
        raise HTTPException(404, "Sync run not found.")
    return repository.public(result)


@router.post("/runs/{run_id}/verify")
def verify(request: Request, run_id: str) -> dict[str, Any]:
    try:
        return service(request).reconcile(run_id)
    except SyncError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/runs/{run_id}/release")
def release(request: Request, run_id: str) -> dict[str, bool]:
    try:
        service(request).release(run_id)
    except SyncError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"released": True}
