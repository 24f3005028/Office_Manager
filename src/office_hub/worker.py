"""Durable single-worker execution loop."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from .config import Settings
from .database import Database
from .repository import JobRepository
from .tasks import get_task
from .tasks.base import TaskContext
from .whatsapp.models import ReportRequest
from .whatsapp.provider import WhatsAppProviderUnavailable
from .whatsapp.service import report_message, send_report_result

logger = logging.getLogger(__name__)


class JobWorker:
    """Claim and execute one job at a time in a daemon thread."""

    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self.run_forever,
            name="office-hub-worker",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        self._thread = None

    def run_forever(self) -> None:
        while not self._stop_event.is_set():
            did_work = self.run_once()
            if not did_work:
                self._stop_event.wait(self.settings.worker_poll_seconds)

    def run_once(self) -> bool:
        with self.database.session_factory() as session:
            repository = JobRepository(session)
            job = repository.claim_next()
            if job is None:
                return False

        task = get_task(job.task_name)
        if task is None:
            self._fail(job.id, f"Unknown task: {job.task_name}")
            return True

        context = TaskContext(
            settings=self.settings,
            job_id=job.id,
            dry_run=job.dry_run,
            logger=logging.getLogger(f"office_hub.task.{job.task_name}"),
        )
        try:
            result = task.execute(job.payload, context)
        except Exception as exc:  # Keep the worker alive when one job fails.
            logger.exception("Job failed: %s", job.id)
            self._fail(job.id, str(exc))
        else:
            with self.database.session_factory() as session:
                JobRepository(session).mark_succeeded(
                    job.id,
                    {"summary": result.summary, **result.data},
                )
            self._notify_whatsapp(job.id, job.payload, result.data)
        return True

    def _fail(self, job_id: str, message: str) -> None:
        with self.database.session_factory() as session:
            JobRepository(session).mark_failed(job_id, message)

    def _notify_whatsapp(
        self,
        job_id: str,
        payload: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        recipient = payload.get("reply_to")
        if not isinstance(recipient, str) or result.get("dispatch") != "completed":
            return
        artifact_value = result.get("artifact")
        artifact: Path | None = None
        if isinstance(artifact_value, str):
            candidate = (self.settings.resolved_output_dir / artifact_value).resolve()
            if candidate.is_relative_to(self.settings.resolved_output_dir.resolve()):
                artifact = candidate
        period = result.get("period", {})
        request = ReportRequest(
            report_type=str(result.get("report_type", "profit_loss")),
            start_date=str(period.get("start", "")),
            end_date=str(period.get("end", "")),
            display_name=(
                "Profit & Loss"
                if result.get("report_type") == "profit_loss"
                else "Balance Sheet"
            ),
        )
        try:
            receipt = send_report_result(
                self.settings,
                recipient,
                report_message(
                    request,
                    result.get("totals", {}),
                    bool(result.get("review_required")),
                ),
                artifact,
                f"office-hub:{payload.get('provider_message_id', 'job')}",
            )
        except WhatsAppProviderUnavailable as exc:
            logger.warning("WhatsApp report delivery was not performed: %s", exc)
            self._record_event(job_id, "WARNING", "WhatsApp delivery was not performed")
        except Exception:
            logger.exception("WhatsApp report delivery failed for job_id=%s", job_id)
            self._record_event(job_id, "WARNING", "WhatsApp delivery failed")
        else:
            logger.info("WhatsApp report delivery status=%s", receipt.status)
            self._record_event(job_id, "INFO", f"WhatsApp delivery status={receipt.status}")

    def _record_event(self, job_id: str, level: str, message: str) -> None:
        with self.database.session_factory() as session:
            repository = JobRepository(session)
            repository.add_event(job_id, level, message)
            session.commit()
