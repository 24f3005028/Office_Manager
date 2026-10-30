"""Pydantic request and response schemas for the HTTP API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DocumentCategory = Literal["bills", "credit_notes", "debit_notes"]
DateSource = Literal["busy", "pdf", "file_fallback"]
MatchStatus = Literal[
    "matched", "unmatched", "ambiguous", "series_mismatch_warning", "pdf_extracted"
]


class DocumentMetadataResponse(BaseModel):
    file_id: str
    category: DocumentCategory
    file_name: str
    relative_path: str
    size_bytes: int
    modified_at: datetime
    root_index: int
    effective_date: date
    date_source: DateSource
    match_status: MatchStatus
    matched_voucher_no: str | None = None


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


class BusyLedgerSampleKey(BaseModel):
    category: DocumentCategory
    raw_voucher_no: str
    canonical_series: str
    fy: str
    serial: int
    voucher_date: date
    party_name: str


class BusyLedgerFileResult(BaseModel):
    filename: str
    category: DocumentCategory | None
    detected_headers: dict[str, str]
    rows_found: int
    rows_imported: int
    sample_keys: list[BusyLedgerSampleKey]
    warnings: list[str]
    min_date: date | None
    max_date: date | None
    deleted: bool


class BusyLedgerImportResponse(BaseModel):
    dry_run: bool
    files: list[BusyLedgerFileResult]
    rows_found: int
    rows_imported: int
    warnings: list[str]


class BusyLedgerCategoryStatus(BaseModel):
    category: DocumentCategory
    total_vouchers: int
    min_date: date | None
    max_date: date | None


class BusyLedgerStatusResponse(BaseModel):
    last_sync_at: datetime | None
    last_sync_filename: str | None
    total_vouchers: int
    categories: list[BusyLedgerCategoryStatus]


class PounchaSyncRunResponse(BaseModel):
    run_id: str
    trigger_type: str
    start_date: date
    end_date: date
    exported_sale_count: int
    already_in_sheet_count: int
    appended_count: int
    status: Literal["queued", "running", "success", "failed", "skipped"]
    error_message: str | None
    warnings: list[str]
    started_at: datetime | None
    completed_at: datetime | None


class PounchaSchedulerStatusResponse(BaseModel):
    enabled: bool
    running: bool
    timezone: str
    next_run_at: datetime | None
    waiting_for_busy: bool
    last_check_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None


class PounchaSyncStatusResponse(BaseModel):
    configured: bool
    sheets_configured: bool
    busy_configured: bool
    sync_enabled: bool
    scheduler: PounchaSchedulerStatusResponse
    last_run: PounchaSyncRunResponse | None
    active_run: PounchaSyncRunResponse | None
    recent_runs: list[PounchaSyncRunResponse]


class PounchaSyncRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: date | None = None
    end_date: date | None = None


class PounchaSyncQueuedResponse(BaseModel):
    run_id: str
    status: Literal["queued", "running"]
