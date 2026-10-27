"""Send-job orchestration and sequential worker."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import date

from app.domains.documents.models import natural_document_sort_key
from app.domains.documents.service import DocumentService
from app.domains.send_jobs.models import ClaimedFile, JobFileInput, SendJobRecord
from app.domains.send_jobs.repository import SendJobRepository
from app.integrations.whatsapp.client import (
    BridgeSendError,
    SendReceipt,
    WhatsAppBridge,
    classify_send_error,
)
from app.integrations.whatsapp.readiness import BridgeReadiness

MAX_SEND_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 3.0
_MAX_ERROR_LENGTH = 240


def format_date_label(value: date) -> str:
    """Render a calendar date the way the user reads it, e.g. 21.10.26."""

    return f"{value:%d.%m.%y}"


def describe_send_error(exc: BaseException) -> str:
    """A short single-line reason that is safe to persist and show in the UI."""

    text = " ".join((str(exc) or type(exc).__name__).split())
    if len(text) > _MAX_ERROR_LENGTH:
        text = text[: _MAX_ERROR_LENGTH - 3].rstrip() + "…"
    return text or type(exc).__name__


class SendJobService:
    def __init__(
        self,
        repository: SendJobRepository,
        documents: DocumentService,
        bridge: WhatsAppBridge,
        readiness: BridgeReadiness | None = None,
    ) -> None:
        self.repository = repository
        self.documents = documents
        self.bridge = bridge
        self.readiness = readiness or BridgeReadiness(
            bridge,
            lambda: [
                str(path)
                for paths in documents.scanner.roots_by_category.values()
                for path in paths
            ],
        )
        self._lock = asyncio.Lock()
        self._active: ClaimedFile | None = None
        self._pending_persistence: Callable[[], None] | None = None

    def create(self, file_ids: Sequence[str], recipient: str, message: str | None) -> SendJobRecord:
        normalized_recipient = recipient.strip()
        if not normalized_recipient:
            raise ValueError("recipient is required")
        unique_ids = list(dict.fromkeys(file_ids))
        if not unique_ids:
            raise ValueError("At least one document is required")
        previews = self.documents.get_previews(unique_ids)
        if len(previews) != len(unique_ids):
            missing = next(file_id for file_id in unique_ids if file_id not in previews)
            raise ValueError(f"Document not found: {missing}")
        # Preview and send order are authoritative and identical: type, natural
        # prefix/number, then configured root order. Dates never reorder documents.
        inputs: list[JobFileInput] = []
        ordered = sorted(previews.values(), key=natural_document_sort_key)
        for position, document in enumerate(ordered):
            # The scanner already validated this path. Re-validate before persisting it so a
            # symlink or root configuration cannot introduce an out-of-root send path.
            validated_path = self.documents.validate_for_send(document.category, str(document.path))
            inputs.append(
                JobFileInput(
                    file_id=document.file_id,
                    category=document.category,
                    path=validated_path,
                    file_name=document.file_name,
                    position=position,
                    date_label=format_date_label(document.modified_at.astimezone().date()),
                )
            )
        return self.repository.create(
            job_id=uuid.uuid4().hex,
            recipient=normalized_recipient,
            message=message,
            files=inputs,
        )

    def list(self, limit: int = 100) -> list[SendJobRecord]:
        return self.repository.list(limit=max(1, min(limit, 500)))

    def get(self, job_id: str) -> SendJobRecord | None:
        return self.repository.get(job_id)

    def cancel(self, job_id: str) -> SendJobRecord | None:
        return self.repository.cancel(job_id)

    async def process_once(self) -> bool:
        # Serialize manual calls as well as the worker. A claimed file stays active
        # across persistence errors; no external operation is repeated to repair SQLite.
        async with self._lock:
            return await self._process_once()

    async def _process_once(self) -> bool:
        if self._pending_persistence is not None:
            self._flush_persistence()
            return True
        if self._active is not None and self._cancel_if_requested(self._active):
            return True
        await self.readiness.refresh()
        if not self.readiness.ready:
            return False
        if self._active is None:
            self._active = self.repository.claim_next_file()
        claimed = self._active
        if claimed is None:
            return False
        if self._cancel_if_requested(claimed):
            return True
        try:
            self.documents.validate_for_send(claimed.category, claimed.path)
        except ValueError as exc:
            error = describe_send_error(exc)
            self._persist(lambda: self._finish(
                claimed, "failed", error,
                error_code="INVALID_DOCUMENT", outcome="not_started",
            ))
            return True
        if claimed.message and not self.repository.is_intro_sent(claimed.job_id):
            receipt = await self._send(
                claimed, "opening message", claimed.intro_operation_id,
                lambda: self.bridge.send_text(
                    recipient=claimed.recipient, text=claimed.message or "",
                    operation_id=claimed.intro_operation_id, generation=self.readiness.generation,
                ),
            )
            if receipt is None:
                return True
            intro_message_id = receipt.message_id
            self._persist(lambda: self.repository.mark_intro_sent(
                claimed.job_id, intro_message_id,
            ))
        if self._cancel_if_requested(claimed):
            return True
        await self.readiness.refresh()
        if not self.readiness.ready:
            return False
        if (
            claimed.date_label and claimed.label_operation_id
            and not self.repository.is_label_already_sent(
                claimed.job_id, claimed.label_operation_id,
            )
        ):
            receipt = await self._send(
                claimed, "date label", claimed.label_operation_id,
                lambda: self.bridge.send_text(
                    recipient=claimed.recipient, text=claimed.date_label or "",
                    operation_id=claimed.label_operation_id or "",
                    generation=self.readiness.generation,
                ),
            )
            if receipt is None:
                return True
            label_message_id = receipt.message_id
            self._persist(lambda: self.repository.mark_label_sent(
                claimed.job_id, claimed.file_row_id, label_message_id,
            ))
        if self._cancel_if_requested(claimed):
            return True
        # Roots or the bridge generation may have changed while a text send was awaiting
        # its receipt; do not start the PDF until the current generation is synchronized.
        await self.readiness.refresh()
        if not self.readiness.ready:
            return False
        try:
            path = self.documents.validate_for_send(claimed.category, claimed.path)
        except ValueError as exc:
            error = describe_send_error(exc)
            self._persist(lambda: self._finish(
                claimed, "failed", error,
                error_code="INVALID_DOCUMENT", outcome="not_started",
            ))
            return True
        receipt = await self._send(
            claimed, "document", claimed.operation_id,
            lambda: self.bridge.send_document(
                recipient=claimed.recipient, file_path=path, message=None,
                operation_id=claimed.operation_id, generation=self.readiness.generation,
            ),
        )
        if receipt is not None:
            # An accepted file remains sent even if cancellation raced with its receipt.
            document_message_id = receipt.message_id
            self._persist(lambda: self._finish(claimed, "sent", message_id=document_message_id))
        return True

    def _persist(self, action: Callable[[], None]) -> None:
        self._pending_persistence = action
        self._flush_persistence()

    def _flush_persistence(self) -> None:
        if self._pending_persistence is not None:
            self._pending_persistence()
            self._pending_persistence = None

    def _finish(
        self, claimed: ClaimedFile, status: str, error: str | None = None, *,
        message_id: str | None = None, error_code: str | None = None,
        outcome: str | None = None, attempt_count: int | None = None,
    ) -> None:
        self.repository.mark_file_result(
            claimed.job_id, claimed.file_row_id, status, error,
            message_id=message_id, error_code=error_code, outcome=outcome,
            attempt_count=attempt_count,
        )
        self._active = None

    def _cancel_if_requested(self, claimed: ClaimedFile) -> bool:
        if self.repository.is_cancel_requested(claimed.job_id):
            self._persist(lambda: self._finish(claimed, "cancelled"))
            return True
        return False

    async def _send(
        self, claimed: ClaimedFile, what: str, operation_id: str,
        action: Callable[[], Awaitable[SendReceipt]],
    ) -> SendReceipt | None:
        try:
            receipt = await action()
            if (
                not isinstance(receipt, SendReceipt) or receipt.operation_id != operation_id
                or not receipt.message_id.strip()
            ):
                raise BridgeSendError(
                    "Invalid bridge send receipt", code="INVALID_SEND_RECEIPT",
                    retryable=False, outcome="unknown",
                )
            return receipt
        except Exception as exc:
            await self._handle_send_failure(claimed, classify_send_error(exc), what=what)
            return None

    async def _handle_send_failure(
        self, claimed: ClaimedFile, exc: BridgeSendError, *, what: str = "document"
    ) -> None:
        reason = describe_send_error(exc)
        error = reason if what == "document" else f"Could not send the {what}: {reason}"
        if exc.outcome == "unknown":
            self._persist(lambda: self._finish(
                claimed, "unknown", error, error_code=exc.code, outcome="unknown",
                attempt_count=claimed.attempt_count + 1,
            ))
            return
        if exc.session_unavailable or (
            exc.retryable and claimed.attempt_count + 1 < MAX_SEND_ATTEMPTS
        ):
            if exc.session_unavailable:
                self.readiness.invalidate()
            attempts = claimed.attempt_count + (0 if exc.session_unavailable else 1)

            def requeue() -> None:
                self.repository.requeue_file(claimed.job_id, claimed.file_row_id, attempts)
                self._active = None

            self._persist(requeue)
            await asyncio.sleep(RETRY_BACKOFF_SECONDS)
            return
        self._persist(lambda: self._finish(
            claimed, "failed", error, error_code=exc.code, outcome="not_started",
            attempt_count=claimed.attempt_count + 1,
        ))


class SendJobWorker:
    def __init__(self, service: SendJobService, poll_seconds: float = 0.5) -> None:
        self.service = service
        self.poll_seconds = poll_seconds
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self.service.repository.recover_incomplete()
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="send-job-worker")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        await self._task
        self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                async with self._lock:
                    processed = await self.service.process_once()
            except Exception as exc:
                # A crash here (e.g. a transient SQLite error) must not kill the worker
                # silently and strand queued jobs. Only the exception class is logged.
                print(f"Send-job worker iteration failed: {type(exc).__name__}", flush=True)
                processed = False
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=2.0)
                    break
                except TimeoutError:
                    continue
            if processed:
                continue
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
            except TimeoutError:
                continue
