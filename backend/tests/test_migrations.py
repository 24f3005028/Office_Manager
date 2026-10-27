import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from app.db import Database
from app.domains.send_jobs.repository import SendJobRepository

LEGACY_SCHEMA = """
CREATE TABLE send_jobs (
    id TEXT PRIMARY KEY, recipient TEXT NOT NULL, message TEXT, status TEXT NOT NULL,
    cancel_requested INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
    started_at TEXT, finished_at TEXT, error TEXT
);
CREATE TABLE send_job_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES send_jobs(id) ON DELETE CASCADE,
    file_id TEXT NOT NULL, category TEXT NOT NULL, file_path TEXT NOT NULL,
    file_name TEXT NOT NULL, position INTEGER NOT NULL, status TEXT NOT NULL,
    error TEXT, created_at TEXT NOT NULL, sent_at TEXT, UNIQUE(job_id, file_id)
);
"""


@pytest.mark.parametrize("has_labels", [False, True])
def test_populated_legacy_database_migrates_and_recovers_without_replaying_sends(
    tmp_path: Path, has_labels: bool,
) -> None:
    path = tmp_path / "legacy.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(LEGACY_SCHEMA)
        if has_labels:
            connection.execute("ALTER TABLE send_job_files ADD COLUMN date_label TEXT")
            connection.execute(
                "ALTER TABLE send_job_files ADD COLUMN label_sent INTEGER NOT NULL DEFAULT 0"
            )
        for job_id, status, cancel, first_status in [
            ("running", "running", 0, "sending"),
            ("cancel-pending", "running", 1, "sending"),
            ("completed", "completed", 0, "sent"),
            ("queued", "queued", 0, "queued"),
        ]:
            connection.execute(
                "INSERT INTO send_jobs (id, recipient, message, status, cancel_requested, "
                "created_at, started_at) VALUES (?, 'fixture@c.us', 'old intro', ?, ?, ?, ?)",
                (job_id, status, cancel, "2026-10-20T12:00:00+00:00", "2026-10-20T12:01:00+00:00"),
            )
            for position in range(3):
                connection.execute(
                    "INSERT INTO send_job_files (job_id, file_id, category, file_path, file_name, "
                    "position, status, created_at, sent_at) "
                    "VALUES (?, ?, 'bills', ?, ?, ?, ?, ?, ?)",
                    (job_id, f"file-{position}", str(tmp_path / f"Bill {position}.pdf"),
                     f"Bill {position}.pdf", position,
                     first_status if position == 0 or status == "completed" else "queued",
                     "2026-10-20T12:00:00+00:00",
                     "2026-10-20T12:02:00+00:00" if status == "completed" else None),
                )
                if has_labels:
                    connection.execute(
                        "UPDATE send_job_files SET date_label = ?, label_sent = ? "
                        "WHERE job_id = ? AND position = ?",
                        ("21.10.26" if position != 1 else "22.10.26",
                         int(status == "completed"), job_id, position),
                    )
    database = Database(path)
    database.initialize()
    repository = SendJobRepository(database)
    before = repository.list()
    assert len(before) == 4
    assert sum(len(job.files) for job in before) == 12
    assert all(file.attempt_count == 0 for job in before for file in job.files)
    ids = {file.operation_id for job in before for file in job.files}
    assert len(ids) == 12
    assert all(key.startswith("office-") and len(key) == 71 for key in ids)
    if has_labels:
        assert len({file.label_operation_id for file in before[0].files}) == 3
    else:
        assert all(file.date_label is None for job in before for file in job.files)
    database.initialize()
    assert {file.operation_id for job in repository.list() for file in job.files} == ids
    repository.recover_incomplete()
    running = repository.get("running")
    assert running is not None and running.status == "needs_review"
    assert [file.status for file in running.files] == ["unknown", "queued", "queued"]
    cancelled = repository.get("cancel-pending")
    assert cancelled is not None and cancelled.status == "needs_review"
    assert [file.status for file in cancelled.files] == ["unknown", "cancelled", "cancelled"]
    completed = repository.get("completed")
    assert completed is not None and completed.status == "completed"
    assert all(file.status == "sent" and file.sent_at for file in completed.files)
    claimed = repository.claim_next_file()
    assert claimed is not None and claimed.job_id == "queued"
    assert claimed.operation_id in ids
    assert repository.claim_next_file() is None  # A second file cannot bypass an active one.


def test_recovery_finalizes_cancelled_jobs_without_inflight_files(tmp_path: Path) -> None:
    database = Database(tmp_path / "cancel.sqlite3")
    database.initialize()
    with closing(database.connect()) as connection, connection:
        connection.execute(
            "INSERT INTO send_jobs (id, recipient, status, cancel_requested, created_at) "
            "VALUES ('cancelled', 'fixture@c.us', 'running', 1, '2026-10-20T12:00:00+00:00')"
        )
    repository = SendJobRepository(database)
    repository.recover_incomplete()
    saved = repository.get("cancelled")
    assert saved is not None and saved.status == "cancelled"
