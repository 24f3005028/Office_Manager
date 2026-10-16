"""Small transactional repository used by HTTP routes, scheduler, and worker."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from .models import InboundMessage, Job, JobEvent, JobStatus


class JobRepository:
    """Persistence operations that keep commit boundaries explicit."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, task_name: str, payload: dict[str, Any], dry_run: bool) -> Job:
        job = Job(task_name=task_name, payload=payload, dry_run=dry_run)
        self.session.add(job)
        self.session.flush()
        self.add_event(job.id, "INFO", "Job queued")
        self.session.commit()
        return job

    def get(self, job_id: str) -> Job | None:
        return self.session.get(Job, job_id)

    def list_recent(self, limit: int = 50) -> Sequence[Job]:
        statement: Select[Job] = (
            select(Job).order_by(Job.created_at.desc()).limit(max(1, min(limit, 200)))
        )
        return self.session.scalars(statement).all()

    def claim_next(self) -> Job | None:
        """Claim the oldest pending job.

        Office Hub intentionally runs one local worker against SQLite. A future multi-worker
        deployment should replace this transaction with broker-level claiming or row locks.
        """

        statement: Select[Job] = (
            select(Job)
            .where(Job.status == JobStatus.PENDING)
            .order_by(Job.created_at.asc())
            .limit(1)
        )
        job = self.session.scalars(statement).first()
        if job is None:
            return None
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        self.add_event(job.id, "INFO", "Job started")
        self.session.commit()
        return job

    def mark_succeeded(self, job_id: str, result: dict[str, Any]) -> None:
        job = self._required(job_id)
        job.status = JobStatus.SUCCEEDED
        job.result = result
        job.finished_at = datetime.now(UTC)
        self.add_event(job.id, "INFO", "Job completed successfully")
        self.session.commit()

    def mark_failed(self, job_id: str, message: str) -> None:
        job = self._required(job_id)
        job.status = JobStatus.FAILED
        job.error_message = message[:4000]
        job.finished_at = datetime.now(UTC)
        self.add_event(job.id, "ERROR", message[:4000])
        self.session.commit()

    def cancel_pending(self, job_id: str) -> Job | None:
        job = self.get(job_id)
        if job is None or job.status != JobStatus.PENDING:
            return None
        job.status = JobStatus.CANCELLED
        job.finished_at = datetime.now(UTC)
        self.add_event(job.id, "INFO", "Job cancelled")
        self.session.commit()
        return job

    def add_event(self, job_id: str, level: str, message: str) -> JobEvent:
        event = JobEvent(job_id=job_id, level=level.upper(), message=message[:4000])
        self.session.add(event)
        self.session.flush()
        return event

    def events_for(self, job_id: str, limit: int = 100) -> Sequence[JobEvent]:
        statement = (
            select(JobEvent)
            .where(JobEvent.job_id == job_id)
            .order_by(JobEvent.created_at.asc())
            .limit(max(1, min(limit, 500)))
        )
        return self.session.scalars(statement).all()

    def register_inbound_message(
        self,
        provider_message_id: str,
        sender_id: str,
        received_at: datetime,
    ) -> bool:
        """Register a provider message; return False for a replay."""

        if self.session.get(InboundMessage, provider_message_id) is not None:
            return False
        self.session.add(
            InboundMessage(
                provider_message_id=provider_message_id,
                sender_id=sender_id,
                received_at=received_at,
            )
        )
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            return False
        return True

    def _required(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job is None:
            raise LookupError(f"Job not found: {job_id}")
        return job
