from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.api.schemas import CreateSendJobRequest, SendJobResponse
from app.domains.send_jobs.models import SendJobRecord

router = APIRouter(prefix="/send-jobs", tags=["send jobs"])


def _response(record: SendJobRecord) -> SendJobResponse:
    return SendJobResponse.model_validate(record.to_dict())


@router.post("", response_model=SendJobResponse, status_code=status.HTTP_201_CREATED)
def create_send_job(request: Request, payload: CreateSendJobRequest) -> SendJobResponse:
    try:
        job = request.app.state.send_job_service.create(
            file_ids=payload.file_ids, recipient=payload.recipient, message=payload.message
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _response(job)


@router.get("", response_model=list[SendJobResponse])
def list_send_jobs(
    request: Request, limit: int = Query(default=100, ge=1, le=500)
) -> list[SendJobResponse]:
    return [_response(job) for job in request.app.state.send_job_service.list(limit)]


@router.get("/{job_id}", response_model=SendJobResponse)
def get_send_job(request: Request, job_id: str) -> SendJobResponse:
    job = request.app.state.send_job_service.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Send job not found")
    return _response(job)


@router.post("/{job_id}/cancel", response_model=SendJobResponse)
def cancel_send_job(request: Request, job_id: str) -> SendJobResponse:
    job = request.app.state.send_job_service.cancel(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Send job not found")
    return _response(job)
