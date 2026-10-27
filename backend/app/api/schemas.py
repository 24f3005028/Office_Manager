"""Pydantic request and response schemas for the HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DocumentCategory = Literal["bills", "credit_notes", "debit_notes"]


class DocumentMetadataResponse(BaseModel):
    file_id: str
    category: DocumentCategory
    file_name: str
    relative_path: str
    size_bytes: int
    modified_at: datetime


class CreateSendJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_ids: list[str] = Field(min_length=1, max_length=500)
    recipient: str = Field(min_length=1, max_length=200)
    message: str | None = Field(default=None, max_length=4096)


class JobFileResponse(BaseModel):
    file_id: str
    category: DocumentCategory
    file_name: str
    date_label: str | None = None
    status: Literal["queued", "sending", "sent", "failed", "cancelled", "unknown"]
    error: str | None
    sent_at: datetime | None
    operation_id: str
    message_id: str | None
    label_operation_id: str | None
    label_message_id: str | None
    attempt_count: int
    error_code: str | None
    outcome: Literal["not_started", "unknown"] | None


class SendJobResponse(BaseModel):
    job_id: str
    recipient: str
    message: str | None
    status: Literal["queued", "running", "completed", "failed", "cancelled", "needs_review"]
    cancel_requested: bool
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    files: list[JobFileResponse]
    intro_sent: bool
    intro_operation_id: str
    intro_message_id: str | None
