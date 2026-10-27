import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest
from app.domains.send_jobs import service as service_module
from app.domains.send_jobs.service import SendJobService
from app.integrations.whatsapp.client import BridgeSendError, HttpWhatsAppBridge, SendReceipt

from tests.fakes import FakeBridge
from tests.test_send_jobs import FlakyBridge, make_service


@pytest.mark.parametrize("failure", [
    httpx.ReadTimeout("fixture timeout"), httpx.WriteTimeout("fixture timeout"),
    RuntimeError("unclassified failure"),
    BridgeSendError("Incomplete journal", code="OPERATION_UNKNOWN", retryable=True,
                    outcome="unknown"),
])
async def test_unknown_pdf_outcome_blocks_subsequent_files_and_survives_cancel_and_restart(
    tmp_path: Path, failure: Exception,
) -> None:
    bridge = FlakyBridge(100, lambda: failure)
    service, _ = make_service(tmp_path, bridge)
    documents = service.documents.list_documents()
    job = service.create([document.file_id for document in documents], "fixture@c.us", "intro")
    assert await service.process_once()
    assert not await service.process_once()
    saved = service.get(job.job_id)
    assert saved is not None
    assert saved.status == "needs_review"
    assert [file.status for file in saved.files] == ["unknown", "queued"]
    assert saved.files[0].outcome == "unknown"
    assert saved.files[0].message_id is None
    assert saved.intro_sent
    assert bridge.calls == 1
    cancelled = service.cancel(job.job_id)
    assert cancelled is not None
    assert cancelled.status == "needs_review"
    assert cancelled.cancel_requested
    assert [file.status for file in cancelled.files] == ["unknown", "cancelled"]
    service.repository.recover_incomplete()
    restarted = SendJobService(service.repository, service.documents, bridge)
    assert not await restarted.process_once()
    assert service.list()[0].status == "needs_review"
    assert bridge.calls == 1


@pytest.mark.parametrize("stage", ["intro", "label"])
async def test_unknown_text_outcome_prevents_the_pdf_and_keeps_intro_unacknowledged(
    tmp_path: Path, stage: str,
) -> None:
    class UnknownText(FakeBridge):
        async def send_text(self, **kwargs: Any) -> SendReceipt:
            if (kwargs["text"] == "intro") == (stage == "intro"):
                raise httpx.ReadTimeout("fixture lost acknowledgment")
            return await super().send_text(**kwargs)

    service, bridge = make_service(tmp_path, UnknownText())
    job = service.create([item.file_id for item in service.documents.list_documents()],
                         "fixture@c.us", "intro")
    assert await service.process_once()
    assert not await service.process_once()
    saved = service.get(job.job_id)
    assert saved is not None
    assert saved.status == "needs_review"
    assert saved.intro_sent is (stage == "label")
    assert bridge.sent == []


@pytest.mark.parametrize("stage", ["intro", "label"])
async def test_cancellation_after_text_ack_prevents_all_later_operations(
    tmp_path: Path, stage: str,
) -> None:
    service, bridge = make_service(tmp_path)
    job = service.create([item.file_id for item in service.documents.list_documents()],
                         "fixture@c.us", "intro")

    def after_text(text: str) -> None:
        if text == "intro":
            saved = service.get(job.job_id)
            assert saved is not None and not saved.intro_sent
        if (text == "intro") == (stage == "intro"):
            service.cancel(job.job_id)

    bridge.after_text = after_text
    assert await service.process_once()
    assert not await service.process_once()
    saved = service.get(job.job_id)
    assert saved is not None
    assert saved.status == "cancelled"
    assert saved.intro_sent
    assert saved.intro_message_id is not None
    assert bridge.sent == []
    assert len(bridge.texts) == (1 if stage == "intro" else 2)


async def test_cancellation_during_accepted_pdf_keeps_its_receipt(tmp_path: Path) -> None:
    class CancelDuringPDF(FakeBridge):
        async def send_document(self, **kwargs: Any) -> SendReceipt:
            service.cancel(job.job_id)
            return await super().send_document(**kwargs)

    service, bridge = make_service(tmp_path, CancelDuringPDF())
    job = service.create([item.file_id for item in service.documents.list_documents()],
                         "fixture@c.us", None)
    assert await service.process_once()
    saved = service.get(job.job_id)
    assert saved is not None
    assert saved.status == "cancelled"
    assert [file.status for file in saved.files] == ["sent", "cancelled"]
    assert saved.files[0].message_id == f"message-{saved.files[0].operation_id}"
    assert len(bridge.sent) == 1


@pytest.mark.parametrize("message", [None, ""])
async def test_empty_intro_is_respected_and_one_label_covers_a_contiguous_date_run(
    tmp_path: Path, message: str | None,
) -> None:
    service, bridge = make_service(tmp_path)
    job = service.create([item.file_id for item in service.documents.list_documents()],
                         "fixture@c.us", message)
    while await service.process_once():
        pass
    saved = service.get(job.job_id)
    assert saved is not None and saved.status == "completed"
    assert not saved.intro_sent
    assert saved.intro_message_id is None
    assert bridge.texts == [saved.files[0].date_label]
    assert saved.files[0].label_operation_id == saved.files[1].label_operation_id
    assert len({file.operation_id for file in saved.files}) == 2
    assert len(bridge.sent) == 2


@pytest.mark.parametrize("method", ["mark_intro_sent", "mark_label_sent", "mark_file_result"])
@pytest.mark.parametrize("after_commit", [False, True])
async def test_post_send_database_failure_retries_persistence_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str, after_commit: bool,
) -> None:
    service, bridge = make_service(tmp_path)
    job = service.create([item.file_id for item in service.documents.list_documents()],
                         "fixture@c.us", "intro")
    original = getattr(service.repository, method)
    calls = 0

    def fail_once(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            if after_commit:
                original(*args, **kwargs)
            raise sqlite3.OperationalError("fixture locked")
        original(*args, **kwargs)

    monkeypatch.setattr(service.repository, method, fail_once)
    with pytest.raises(sqlite3.OperationalError, match="fixture locked"):
        await service.process_once()
    before = list(bridge.events)
    assert await service.process_once()  # Retries only the acknowledgment transaction.
    assert bridge.events == before
    while await service.process_once():
        pass
    saved = service.get(job.job_id)
    assert saved is not None and saved.status == "completed"
    assert len(bridge.sent) == 2
    assert bridge.texts.count("intro") == 1
    assert len(bridge.texts) == 2
    assert len({key for _, _, key in bridge.events}) == len(bridge.events)
    assert all(file.message_id for file in saved.files)


async def test_crash_before_receipt_persistence_recovers_to_review_without_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, bridge = make_service(tmp_path)
    job = service.create([item.file_id for item in service.documents.list_documents()],
                         "fixture@c.us", None)

    def unavailable(*args: Any, **kwargs: Any) -> None:
        raise sqlite3.OperationalError("fixture unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(service.repository, "mark_file_result", unavailable)
        with pytest.raises(sqlite3.OperationalError):
            await service.process_once()
    assert len(bridge.sent) == 1
    service.repository.recover_incomplete()
    restarted = SendJobService(service.repository, service.documents, bridge)
    assert not await restarted.process_once()
    saved = restarted.get(job.job_id)
    assert saved is not None and saved.status == "needs_review"
    assert saved.files[0].status == "unknown"
    assert saved.files[0].error_code == "INTERRUPTED_SEND"
    assert saved.files[1].status == "queued"
    assert len(bridge.sent) == 1


async def test_session_race_requeues_without_consuming_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service_module, "RETRY_BACKOFF_SECONDS", 0)
    bridge = FlakyBridge(1, lambda: BridgeSendError(
        "Session changed after ready check", code="GENERATION_MISMATCH", retryable=True,
        outcome="not_started", session_unavailable=True,
    ))
    service, _ = make_service(tmp_path, bridge)
    job = service.create([service.documents.list_documents()[0].file_id], "fixture@c.us", None)
    assert await service.process_once()
    saved = service.get(job.job_id)
    assert saved is not None and saved.files[0].attempt_count == 0
    bridge.generation += 1
    assert await service.process_once()
    assert bridge.operation_ids[0] == bridge.operation_ids[1]
    saved = service.get(job.job_id)
    assert saved is not None and saved.status == "completed"
    assert bridge.send_generations[-1] == bridge.generation


async def test_concurrent_process_calls_do_not_send_the_intro_or_files_twice(
    tmp_path: Path,
) -> None:
    service, bridge = make_service(tmp_path)
    job = service.create([item.file_id for item in service.documents.list_documents()],
                         "fixture@c.us", "intro")
    await asyncio.gather(*(service.process_once() for _ in range(5)))
    saved = service.get(job.job_id)
    assert saved is not None and saved.status == "completed"
    assert len(bridge.sent) == 2
    assert bridge.texts.count("intro") == 1


@pytest.mark.parametrize("stage", ["intro", "label"])
async def test_safe_text_retry_uses_the_same_operation_id_and_acknowledges_only_after_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str,
) -> None:
    monkeypatch.setattr(service_module, "RETRY_BACKOFF_SECONDS", 0)

    class RetryText(FakeBridge):
        attempted_keys: list[str]

        def __init__(self) -> None:
            super().__init__()
            self.attempted_keys = []

        async def send_text(self, **kwargs: Any) -> SendReceipt:
            if (kwargs["text"] == "intro") == (stage == "intro"):
                self.attempted_keys.append(kwargs["operation_id"])
                if len(self.attempted_keys) == 1:
                    raise httpx.ConnectError("fixture refused connection")
            return await super().send_text(**kwargs)

    service, bridge = make_service(tmp_path, RetryText())
    job = service.create([service.documents.list_documents()[0].file_id], "fixture@c.us", "intro")
    assert await service.process_once()
    saved = service.get(job.job_id)
    assert saved is not None and saved.intro_sent is (stage == "label")
    assert bridge.sent == []
    assert await service.process_once()
    saved = service.get(job.job_id)
    assert saved is not None and saved.status == "completed"
    assert saved.intro_sent and saved.intro_message_id
    assert len(bridge.attempted_keys) == 2
    assert len(set(bridge.attempted_keys)) == 1
    assert len(bridge.texts) == 2
    assert len(bridge.sent) == 1


@pytest.mark.parametrize("response_kind", ["incomplete_journal", "wrong_receipt", "unclassified"])
async def test_http_pdf_error_or_invalid_receipt_persists_review_and_blocks_replay(
    tmp_path: Path, response_kind: str,
) -> None:
    document_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal document_calls
        if request.url.path == "/status":
            return httpx.Response(200, json={"status": "ready", "connected": True, "generation": 7})
        if request.url.path == "/allowed-roots":
            return httpx.Response(200, json={"status": "ok"})
        payload = json.loads(request.content)
        assert payload["generation"] == 7
        if request.url.path == "/send-text":
            return httpx.Response(200, json={
                "status": "sent", "message_id": "text-receipt",
                "operation_id": payload["operation_id"],
            })
        assert request.url.path == "/send-document"
        document_calls += 1
        if response_kind == "incomplete_journal":
            return httpx.Response(409, json={
                "error": "Incomplete journal", "code": "OPERATION_UNKNOWN",
                "retryable": False, "outcome": "unknown",
            })
        if response_kind == "wrong_receipt":
            return httpx.Response(200, json={
                "status": "sent", "message_id": "wrong", "operation_id": "another-operation",
            })
        return httpx.Response(503, text="unclassified gateway failure")

    bridge = HttpWhatsAppBridge("http://fixture-bridge", transport=httpx.MockTransport(handler))
    service, _ = make_service(tmp_path, bridge)
    job = service.create([item.file_id for item in service.documents.list_documents()],
                         "fixture@c.us", None)
    try:
        assert await service.process_once()
        assert not await service.process_once()
    finally:
        await bridge.close()
    saved = service.get(job.job_id)
    assert saved is not None and saved.status == "needs_review"
    assert [file.status for file in saved.files] == ["unknown", "queued"]
    assert saved.files[0].outcome == "unknown"
    assert document_calls == 1
