import asyncio
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from app.db import Database
from app.domains.documents.scanner import DocumentScanner
from app.domains.documents.service import DocumentService
from app.domains.send_jobs import service as send_jobs_service
from app.domains.send_jobs.repository import SendJobRepository
from app.domains.send_jobs.service import SendJobService, SendJobWorker
from app.integrations.whatsapp.client import BridgeSendError, SendReceipt

from tests.fakes import FakeBridge


class FlakyBridge(FakeBridge):
    """Fails actual PDF sends, after the intro and date label have succeeded."""

    def __init__(self, failures: int, exc_factory: Any) -> None:
        super().__init__()
        self.failures = failures
        self.exc_factory = exc_factory
        self.calls = 0
        self.operation_ids: list[str] = []

    async def send_document(
        self, *, recipient: str, file_path: Path, message: str | None,
        operation_id: str, generation: int | None = None,
    ) -> SendReceipt:
        self.calls += 1
        self.operation_ids.append(operation_id)
        if self.calls <= self.failures:
            raise self.exc_factory()
        return await super().send_document(
            recipient=recipient, file_path=file_path, message=message,
            operation_id=operation_id, generation=generation,
        )


def make_service(tmp_path: Path, bridge: Any | None = None) -> tuple[SendJobService, Any]:
    root = tmp_path / "bills"
    root.mkdir(exist_ok=True)
    (root / "Bill 1.pdf").write_bytes(b"one")
    (root / "Bill 2.pdf").write_bytes(b"two")
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    documents = DocumentService(DocumentScanner({"bills": (root,)}))
    resolved_bridge = bridge or FakeBridge()
    service = SendJobService(SendJobRepository(database), documents, resolved_bridge)
    return service, resolved_bridge


def build_http_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://bridge/send-document")
    response = httpx.Response(status_code, request=request, json={
        "error": f"{status_code} temporarily unavailable", "code": "TEMPORARY_SEND_FAILURE",
        "outcome": "not_started", "retryable": True,
    })
    return httpx.HTTPStatusError(
        f"{status_code} response", request=request, response=response
    )


def _set_day(path: Path, day: datetime) -> None:
    stamp = day.timestamp()
    os.utime(path, (stamp, stamp))


def make_two_day_service(tmp_path: Path) -> tuple[SendJobService, Any]:
    """Bills folder with documents from two different days, created out of order."""

    root = tmp_path / "bills"
    root.mkdir(exist_ok=True)
    old = root / "HST-1 old.pdf"
    old.write_bytes(b"old")
    _set_day(old, datetime(2026, 10, 22, 15, 0))
    second = root / "HST-2 new.pdf"
    second.write_bytes(b"new")
    _set_day(second, datetime(2026, 10, 21, 10, 0))
    late = root / "HST-11 new.pdf"
    late.write_bytes(b"late")
    _set_day(late, datetime(2026, 10, 22, 10, 0))
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    documents = DocumentService(DocumentScanner({"bills": (root,)}))
    bridge = FakeBridge()
    return SendJobService(SendJobRepository(database), documents, bridge), bridge


def test_create_orders_by_effective_date_then_category_and_natural_name(
    tmp_path: Path,
) -> None:
    service, _ = make_two_day_service(tmp_path)
    file_ids = [record.file_id for record in service.documents.list_documents("bills")]

    job = service.create(file_ids, "+911234567890", None)

    assert [(file.file_name, file.date_label) for file in job.files] == [
        ("HST-2 new.pdf", "21.10.26"),
        ("HST-1 old.pdf", "22.10.26"),
        ("HST-11 new.pdf", "22.10.26"),
    ]


async def test_one_date_label_covers_each_contiguous_date(tmp_path: Path) -> None:
    service, bridge = make_two_day_service(tmp_path)
    file_ids = [record.file_id for record in service.documents.list_documents("bills")]
    job = service.create(file_ids, "+911234567890", "opening note")

    while await service.process_once():
        pass

    saved = service.get(job.job_id)
    assert saved is not None
    assert saved.status == "completed"
    assert bridge.texts == ["opening note", "21.10.26", "22.10.26"]
    assert len({key for kind, _, key in bridge.events if kind == "text"}) == 3
    assert [(kind, value) for kind, value, _ in bridge.events] == [
        ("text", "opening note"),
        ("text", "21.10.26"),
        ("document", "HST-2 new.pdf"),
        ("text", "22.10.26"),
        ("document", "HST-1 old.pdf"),
        ("document", "HST-11 new.pdf"),
    ]
    assert [path.name for _, path, _ in bridge.sent] == [
        "HST-2 new.pdf",
        "HST-1 old.pdf",
        "HST-11 new.pdf",
    ]
    assert all(file.status == "sent" for file in saved.files)


@pytest.mark.parametrize("state", [
    "starting", "authenticated", "qr", "retrying", "disconnected", "auth_failure", "error",
])
async def test_unready_session_waits_without_claiming_or_consuming_attempts(
    tmp_path: Path, state: str,
) -> None:
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    root = tmp_path / "bills"
    root.mkdir(exist_ok=True)
    (root / "Bill A.pdf").write_bytes(b"a")
    (root / "Bill B.pdf").write_bytes(b"b")
    documents = DocumentService(DocumentScanner({"bills": (root,)}))
    bridge = FakeBridge()
    bridge.state = state
    service = SendJobService(SendJobRepository(database), documents, bridge)
    file_ids = [record.file_id for record in documents.list_documents("bills")]
    job = service.create(file_ids, "+911234567890", None)

    for _ in range(5):
        assert await service.process_once() is False

    saved = service.get(job.job_id)
    assert saved is not None
    assert saved.status == "queued"
    assert saved.started_at is None
    assert [file.status for file in saved.files] == ["queued", "queued"]
    assert [file.attempt_count for file in saved.files] == [0, 0]
    assert bridge.events == []
    bridge.state = "ready"
    assert await service.process_once() is True
    assert len(bridge.sent) == 1


def make_three_day_multi_category_service(tmp_path: Path) -> tuple[SendJobService, Any]:
    """Four documents per day across bills folder 1/2, CN folder 1 and DN folder 1."""

    roots = {
        ("bills", 0): tmp_path / "bills-folder-1",
        ("bills", 1): tmp_path / "bills-folder-2",
        ("credit_notes", 0): tmp_path / "credit-notes-folder-1",
        ("debit_notes", 0): tmp_path / "debit-notes-folder-1",
    }
    for root in roots.values():
        root.mkdir()
    specs = [
        ("bills", 0, "HST-1 F1.pdf", 25),
        ("bills", 1, "HST-2 F2.pdf", 25),
        ("credit_notes", 0, "CN-1 F1.pdf", 25),
        ("debit_notes", 0, "DN-1 F1.pdf", 25),
        ("bills", 0, "HST-3 F1.pdf", 26),
        ("bills", 1, "HST-4 F2.pdf", 26),
        ("credit_notes", 0, "CN-2 F1.pdf", 26),
        ("debit_notes", 0, "DN-2 F1.pdf", 26),
        ("bills", 0, "HST-5 F1.pdf", 27),
        ("bills", 1, "HST-6 F2.pdf", 27),
        ("credit_notes", 0, "CN-3 F1.pdf", 27),
        ("debit_notes", 0, "DN-3 F1.pdf", 27),
    ]
    for category, root_index, name, day in specs:
        path = roots[(category, root_index)] / name
        path.write_bytes(b"%PDF-1.4 fixture")
        _set_day(path, datetime(2026, 10, day, 10, 0))
    database = Database(tmp_path / "multi-day.sqlite3")
    database.initialize()
    documents = DocumentService(
        DocumentScanner(
            {
                "bills": (roots[("bills", 0)], roots[("bills", 1)]),
                "credit_notes": (roots[("credit_notes", 0)],),
                "debit_notes": (roots[("debit_notes", 0)],),
            }
        )
    )
    bridge = FakeBridge()
    return SendJobService(SendJobRepository(database), documents, bridge), bridge


async def test_three_dates_emit_exactly_one_header_per_date_in_folder_order(
    tmp_path: Path,
) -> None:
    service, bridge = make_three_day_multi_category_service(tmp_path)
    records = service.documents.list_documents()
    expected_documents = [
        ("HST-1 F1.pdf", "25.10.26"), ("HST-2 F2.pdf", "25.10.26"),
        ("CN-1 F1.pdf", "25.10.26"), ("DN-1 F1.pdf", "25.10.26"),
        ("HST-3 F1.pdf", "26.10.26"), ("HST-4 F2.pdf", "26.10.26"),
        ("CN-2 F1.pdf", "26.10.26"), ("DN-2 F1.pdf", "26.10.26"),
        ("HST-5 F1.pdf", "27.10.26"), ("HST-6 F2.pdf", "27.10.26"),
        ("CN-3 F1.pdf", "27.10.26"), ("DN-3 F1.pdf", "27.10.26"),
    ]
    assert [
        (record.file_name, record.effective_date.strftime("%d.%m.%y"))
        for record in records
    ] == expected_documents

    job = service.create(
        [record.file_id for record in reversed(records)], "+911234567890", None
    )
    assert [(file.file_name, file.date_label) for file in job.files] == expected_documents

    while await service.process_once():
        pass

    saved = service.get(job.job_id)
    assert saved is not None and saved.status == "completed"
    assert bridge.texts == ["25.10.26", "26.10.26", "27.10.26"]
    assert [(kind, value) for kind, value, _ in bridge.events] == [
        ("text", "25.10.26"),
        ("document", "HST-1 F1.pdf"),
        ("document", "HST-2 F2.pdf"),
        ("document", "CN-1 F1.pdf"),
        ("document", "DN-1 F1.pdf"),
        ("text", "26.10.26"),
        ("document", "HST-3 F1.pdf"),
        ("document", "HST-4 F2.pdf"),
        ("document", "CN-2 F1.pdf"),
        ("document", "DN-2 F1.pdf"),
        ("text", "27.10.26"),
        ("document", "HST-5 F1.pdf"),
        ("document", "HST-6 F2.pdf"),
        ("document", "CN-3 F1.pdf"),
        ("document", "DN-3 F1.pdf"),
    ]
    assert all(file.status == "sent" for file in saved.files)


async def test_job_processes_files_sequentially_and_persists_status(tmp_path: Path) -> None:
    service, bridge = make_service(tmp_path)
    file_ids = [record.file_id for record in service.documents.list_documents("bills")]
    job = service.create(file_ids, "+911234567890", "Here are the bills")

    assert job.status == "queued"
    assert [file.status for file in job.files] == ["queued", "queued"]
    assert await service.process_once() is True
    assert await service.process_once() is True
    assert await service.process_once() is False

    saved = service.get(job.job_id)
    assert saved is not None
    assert saved.status == "completed"
    assert [file.status for file in saved.files] == ["sent", "sent"]
    assert [path.name for _, path, _ in bridge.sent] == ["Bill 1.pdf", "Bill 2.pdf"]


async def test_cancelled_job_does_not_send_queued_files(tmp_path: Path) -> None:
    service, bridge = make_service(tmp_path)
    file_ids = [record.file_id for record in service.documents.list_documents("bills")]
    job = service.create(file_ids, "+911234567890", None)

    cancelled = service.cancel(job.job_id)
    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert [file.status for file in cancelled.files] == ["cancelled", "cancelled"]
    assert await service.process_once() is False
    assert bridge.sent == []


def test_create_scans_documents_once_for_the_whole_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _ = make_service(tmp_path)
    file_ids = [record.file_id for record in service.documents.list_documents("bills")]
    original_scan = service.documents.scanner.scan
    scan_count = 0

    def counting_scan(*args: Any, **kwargs: Any) -> Any:
        nonlocal scan_count
        scan_count += 1
        return original_scan(*args, **kwargs)

    monkeypatch.setattr(service.documents.scanner, "scan", counting_scan)
    job = service.create(file_ids, "+911234567890", None)

    assert scan_count == 1
    assert job is not None


def test_create_rejects_missing_document(tmp_path: Path) -> None:
    service, _ = make_service(tmp_path)
    file_ids = [record.file_id for record in service.documents.list_documents("bills")]

    with pytest.raises(ValueError, match="Document not found: missing-id"):
        service.create([*file_ids, "missing-id"], "+911234567890", None)


async def test_transient_send_failure_is_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(send_jobs_service, "RETRY_BACKOFF_SECONDS", 0.0)
    service, _ = make_service(
        tmp_path, bridge=FlakyBridge(1, lambda: build_http_error(502))
    )
    file_ids = [record.file_id for record in service.documents.list_documents("bills")]
    job = service.create([file_ids[0]], "+911234567890", None)

    # First attempt requeues the file; the second one sends it.
    assert await service.process_once() is True
    assert await service.process_once() is True
    assert await service.process_once() is False

    saved = service.get(job.job_id)
    assert saved is not None
    assert saved.status == "completed"
    assert [file.status for file in saved.files] == ["sent"]
    assert [file.error for file in saved.files] == [None]
    assert service.bridge.calls == 2
    assert len(set(service.bridge.operation_ids)) == 1
    assert len(service.bridge.texts) == 1


async def test_persistent_send_failure_marks_file_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(send_jobs_service, "RETRY_BACKOFF_SECONDS", 0.0)
    service, _ = make_service(
        tmp_path, bridge=FlakyBridge(100, lambda: build_http_error(502))
    )
    file_ids = [record.file_id for record in service.documents.list_documents("bills")]
    job = service.create([file_ids[0]], "+911234567890", None)

    for _ in range(send_jobs_service.MAX_SEND_ATTEMPTS):
        assert await service.process_once() is True
    assert await service.process_once() is False

    saved = service.get(job.job_id)
    assert saved is not None
    assert saved.status == "failed"
    assert [file.status for file in saved.files] == ["failed"]
    assert "502" in saved.files[0].error
    assert service.bridge.calls == 3


async def test_non_transient_send_failure_is_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(send_jobs_service, "RETRY_BACKOFF_SECONDS", 0.0)
    service, _ = make_service(
        tmp_path, bridge=FlakyBridge(100, lambda: BridgeSendError(
            "bad path", code="INVALID_PATH", retryable=False, outcome="not_started",
        ))
    )
    file_ids = [record.file_id for record in service.documents.list_documents("bills")]
    job = service.create([file_ids[0]], "+911234567890", None)

    assert await service.process_once() is True
    assert await service.process_once() is False

    saved = service.get(job.job_id)
    assert saved is not None
    assert saved.status == "failed"
    assert [file.status for file in saved.files] == ["failed"]
    assert "bad path" in saved.files[0].error


class FlakyRepository(SendJobRepository):
    """Fails the first claim with an unexpected error to test worker resilience."""

    def __init__(self, database: Database) -> None:
        super().__init__(database)
        self.calls = 0

    def claim_next_file(self) -> Any:
        self.calls += 1
        if self.calls == 1:
            raise sqlite3.OperationalError("database is locked")
        return super().claim_next_file()


async def test_worker_survives_a_transient_worker_error(tmp_path: Path) -> None:
    service, bridge = make_service(tmp_path)
    database_flaky = Database(tmp_path / "flaky.sqlite3")
    database_flaky.initialize()
    flaky_repository = FlakyRepository(database_flaky)
    flaky_service = SendJobService(flaky_repository, service.documents, bridge)

    file_ids = [record.file_id for record in service.documents.list_documents("bills")]
    job = flaky_service.create(file_ids, "+911234567890", None)
    assert job.status == "queued"

    worker = SendJobWorker(flaky_service, poll_seconds=0.01)
    await worker.start()
    try:
        for _ in range(200):
            saved = flaky_service.get(job.job_id)
            if saved is not None and saved.status == "completed":
                break
            await asyncio.sleep(0.02)
        saved = flaky_service.get(job.job_id)
        assert saved is not None
        assert saved.status == "completed"
        assert len(bridge.sent) == len(file_ids)
        assert worker._stop.is_set() is False
    finally:
        await worker.stop()


def test_attempt_count_column_is_added_to_preexisting_databases(tmp_path: Path) -> None:
    """A database created before retries existed gains the column on initialize."""

    database_path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        "CREATE TABLE send_jobs (id TEXT PRIMARY KEY, recipient TEXT NOT NULL, "
        "message TEXT, status TEXT NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0, "
        "created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, error TEXT)"
    )
    connection.close()
    Database(database_path).initialize()

    migrated = sqlite3.connect(database_path)
    try:
        rows = migrated.execute("PRAGMA table_info(send_job_files)").fetchall()
        names = {row[1] for row in rows}
        default_rows = {row[1]: row for row in rows}
        assert "attempt_count" in names
        assert str(default_rows["attempt_count"][4]) == "0"
    finally:
        migrated.close()
