"""Dashboard and JSON API routes."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from ..repository import JobRepository
from ..tasks import available_tasks, get_task
from ..whatsapp.command_parser import WhatsAppCommandError
from ..whatsapp.models import InboundWhatsAppMessage
from ..whatsapp.provider import WhatsAppProviderUnavailable
from ..whatsapp.service import acknowledgement, plan_help_request, send_report_result
from .schemas import JobCreateRequest, WhatsAppInboundRequest

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
router = APIRouter()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def serialize_job(job: Any, repository: JobRepository | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": job.id,
        "task_name": job.task_name,
        "status": job.status.value,
        "dry_run": job.dry_run,
        "payload": job.payload,
        "result": job.result,
        "error_message": job.error_message,
        "created_at": _iso(job.created_at),
        "started_at": _iso(job.started_at),
        "finished_at": _iso(job.finished_at),
    }
    if repository is not None:
        result["events"] = [
            {
                "level": event.level,
                "message": event.message,
                "created_at": _iso(event.created_at),
            }
            for event in repository.events_for(job.id)
        ]
    return result


def _repository(request: Request) -> JobRepository:
    session = request.app.state.db.session_factory()
    # Routes close the session after each operation; the repository stays request-local.
    request.state.db_session = session
    return JobRepository(session)


def _close_session(request: Request) -> None:
    session = getattr(request.state, "db_session", None)
    if session is not None:
        session.close()


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    repository = _repository(request)
    try:
        jobs = repository.list_recent()
        settings = request.app.state.settings
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "jobs": [serialize_job(job) for job in jobs],
                "tasks": available_tasks().values(),
                "settings": settings,
            },
        )
    finally:
        _close_session(request)


@router.get("/health")
def health(request: Request) -> dict[str, str]:
    repository = _repository(request)
    try:
        repository.session.execute(text("SELECT 1"))
        return {"status": "ok", "environment": request.app.state.settings.environment}
    finally:
        _close_session(request)


@router.get("/api/tasks")
def list_tasks() -> list[dict[str, str]]:
    return [
        {"name": task.name, "display_name": task.display_name}
        for task in available_tasks().values()
    ]


@router.get("/api/jobs")
def list_jobs(request: Request, limit: int = 50) -> list[dict[str, Any]]:
    repository = _repository(request)
    try:
        return [serialize_job(job) for job in repository.list_recent(limit)]
    finally:
        _close_session(request)


@router.post("/api/jobs", status_code=status.HTTP_201_CREATED)
def create_job(request: Request, body: JobCreateRequest) -> dict[str, Any]:
    task = get_task(body.task_name)
    if task is None:
        raise HTTPException(status_code=400, detail=f"Unknown task: {body.task_name}")
    settings = request.app.state.settings
    if not body.dry_run and not settings.allow_external_actions:
        raise HTTPException(
            status_code=400,
            detail=(
                "External actions are disabled. Set OFFICE_HUB_ALLOW_EXTERNAL_ACTIONS=true "
                "after review."
            ),
        )

    repository = _repository(request)
    try:
        job = repository.create(body.task_name, body.payload, body.dry_run)
        return serialize_job(job, repository)
    finally:
        _close_session(request)


@router.get("/api/jobs/{job_id}")
def get_job(request: Request, job_id: str) -> dict[str, Any]:
    repository = _repository(request)
    try:
        job = repository.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return serialize_job(job, repository)
    finally:
        _close_session(request)


@router.post("/api/jobs/{job_id}/cancel")
def cancel_job(request: Request, job_id: str) -> dict[str, Any]:
    repository = _repository(request)
    try:
        job = repository.cancel_pending(job_id)
        if job is None:
            existing = repository.get(job_id)
            if existing is None:
                raise HTTPException(status_code=404, detail="Job not found")
            raise HTTPException(status_code=409, detail="Only pending jobs can be cancelled")
        return serialize_job(job, repository)
    finally:
        _close_session(request)


@router.post("/api/whatsapp/inbound", status_code=status.HTTP_202_ACCEPTED)
def receive_whatsapp_message(
    request: Request,
    body: WhatsAppInboundRequest,
) -> dict[str, Any]:
    """Provider-neutral local endpoint for a verified WhatsApp adapter.

    A public provider webhook must verify its signature before calling this endpoint. This route is
    intentionally local/provider-neutral until a concrete WhatsApp provider is selected.
    """

    settings = request.app.state.settings
    if not settings.whatsapp_sender_allowlist:
        raise HTTPException(status_code=503, detail="WhatsApp sender allowlist is not configured")
    if body.sender_id not in settings.whatsapp_sender_allowlist:
        raise HTTPException(status_code=403, detail="Sender is not authorized")

    received_at = body.received_at or datetime.now(UTC)
    message = InboundWhatsAppMessage(
        provider_message_id=body.provider_message_id,
        sender_id=body.sender_id,
        text=body.text,
        received_at=received_at,
    )
    try:
        report_request = plan_help_request(message)
    except WhatsAppCommandError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    repository = _repository(request)
    try:
        if not repository.register_inbound_message(
            body.provider_message_id,
            body.sender_id,
            received_at,
        ):
            return {"status": "duplicate", "provider_message_id": body.provider_message_id}
        use_ui = (
            body.input_file is None
            and settings.allow_external_actions
            and settings.busy_automation_enabled
            and settings.busy_ui_profile_file is not None
            and settings.busy_exe_path is not None
        )
        job = repository.create(
            task_name="busy_exporter",
            payload={
                "report_type": report_request.report_type,
                "start_date": report_request.start_date,
                "end_date": report_request.end_date,
                "mode": "ui" if use_ui else "manual_import",
                "input_file": body.input_file,
                "reply_to": body.sender_id,
                "provider_message_id": body.provider_message_id,
            },
            dry_run=not use_ui,
        )
        return {
            "status": "queued",
            "job_id": job.id,
            "reply": acknowledgement(message, report_request),
            "next_step": "Export the BUSY report into the configured inbox before processing it.",
        }
    finally:
        _close_session(request)


@router.get("/webhooks/whatsapp", response_class=PlainTextResponse)
def verify_whatsapp_webhook(
    request: Request,
    mode: str | None = Query(default=None, alias="hub.mode"),
    verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> PlainTextResponse:
    """Verify a Meta webhook without exposing credentials or accepting unsigned messages."""

    configured = request.app.state.settings.whatsapp_cloud_verify_token
    if (
        mode != "subscribe"
        or configured is None
        or verify_token != configured.get_secret_value()
        or challenge is None
    ):
        raise HTTPException(status_code=403, detail="Webhook verification failed")
    return PlainTextResponse(challenge)


@router.post("/webhooks/whatsapp", status_code=status.HTTP_200_OK)
async def receive_cloud_webhook(request: Request) -> dict[str, str]:
    """Accept the official Cloud API envelope after HMAC verification."""

    settings = request.app.state.settings
    secret = settings.whatsapp_cloud_app_secret
    if secret is None:
        raise HTTPException(status_code=503, detail="WhatsApp app secret is not configured")
    raw_body = await request.body()
    supplied = request.headers.get("x-hub-signature-256", "")
    expected = "sha256=" + hmac.new(
        secret.get_secret_value().encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="Webhook signature verification failed")
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook JSON") from exc

    inbound = _cloud_inbound_request(payload)
    if inbound is None:
        return {"status": "ignored"}
    queued = receive_whatsapp_message(request, inbound)
    if queued.get("status") == "queued":
        try:
            send_report_result(
                settings,
                inbound.sender_id,
                str(queued["reply"]),
                None,
                f"office-hub:ack:{inbound.provider_message_id}",
            )
        except WhatsAppProviderUnavailable:
            # The report remains queued; the dashboard/job event is the source of truth.
            pass
    return {"status": str(queued.get("status", "accepted"))}


def _cloud_inbound_request(payload: Any) -> WhatsAppInboundRequest | None:
    try:
        message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
        text = message["text"]["body"]
        timestamp = datetime.fromtimestamp(int(message["timestamp"]), UTC)
        return WhatsAppInboundRequest(
            provider_message_id=str(message["id"]),
            sender_id=str(message["from"]),
            text=str(text),
            received_at=timestamp,
        )
    except (KeyError, IndexError, TypeError, ValueError):
        return None
