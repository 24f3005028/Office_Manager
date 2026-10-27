"""Send-job persistence and API-facing domain records."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path


def operation_key(job_id: str, kind: str, position: int | None = None) -> str:
    """Stable, opaque journal keys, independent of paths, recipients, and attempts."""

    value = f"{job_id}\0{kind}\0{position}"
    return "office-" + sha256(value.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class JobFileInput:
    file_id: str
    category: str
    path: Path
    file_name: str
    position: int
    date_label: str | None = None


@dataclass(frozen=True, slots=True)
class JobFileRecord:
    row_id: int
    file_id: str
    category: str
    path: str
    file_name: str
    position: int
    date_label: str | None
    status: str
    error: str | None
    sent_at: str | None
    operation_id: str
    message_id: str | None
    label_operation_id: str | None
    label_message_id: str | None
    attempt_count: int
    error_code: str | None
    outcome: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "file_id": self.file_id,
            "category": self.category,
            "file_name": self.file_name,
            "date_label": self.date_label,
            "status": self.status,
            "error": self.error,
            "sent_at": self.sent_at,
            "operation_id": self.operation_id,
            "message_id": self.message_id,
            "label_operation_id": self.label_operation_id,
            "label_message_id": self.label_message_id,
            "attempt_count": self.attempt_count,
            "error_code": self.error_code,
            "outcome": self.outcome,
        }


@dataclass(frozen=True, slots=True)
class SendJobRecord:
    job_id: str
    recipient: str
    message: str | None
    status: str
    cancel_requested: bool
    created_at: str
    started_at: str | None
    finished_at: str | None
    error: str | None
    files: tuple[JobFileRecord, ...]
    intro_sent: bool
    intro_operation_id: str
    intro_message_id: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "recipient": self.recipient,
            "message": self.message,
            "status": self.status,
            "cancel_requested": self.cancel_requested,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "files": [file_record.to_dict() for file_record in self.files],
            "intro_sent": self.intro_sent,
            "intro_operation_id": self.intro_operation_id,
            "intro_message_id": self.intro_message_id,
        }


@dataclass(frozen=True, slots=True)
class ClaimedFile:
    job_id: str
    recipient: str
    message: str | None
    file_row_id: int
    file_id: str
    category: str
    path: str
    file_name: str
    position: int
    date_label: str | None
    label_sent: bool
    attempt_count: int
    operation_id: str
    intro_operation_id: str
    label_operation_id: str | None
