"""Small SQLite database wrapper used by the durable send-job repository."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from app.domains.send_jobs.models import operation_key

SCHEMA = """
CREATE TABLE IF NOT EXISTS send_jobs (
    id TEXT PRIMARY KEY,
    recipient TEXT NOT NULL,
    message TEXT,
    status TEXT NOT NULL,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    intro_sent INTEGER NOT NULL DEFAULT 0,
    intro_operation_id TEXT,
    intro_message_id TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS send_job_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES send_jobs(id) ON DELETE CASCADE,
    file_id TEXT NOT NULL,
    category TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    position INTEGER NOT NULL,
    date_label TEXT,
    label_sent INTEGER NOT NULL DEFAULT 0,
    operation_id TEXT,
    message_id TEXT,
    label_operation_id TEXT,
    label_message_id TEXT,
    status TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    error_code TEXT,
    outcome TEXT,
    created_at TEXT NOT NULL,
    sent_at TEXT,
    UNIQUE(job_id, file_id)
);

CREATE INDEX IF NOT EXISTS idx_send_jobs_status_created
    ON send_jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_send_job_files_queue
    ON send_job_files(status, job_id, position);

CREATE TABLE IF NOT EXISTS workspace_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    document_roots TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as connection, connection:
            connection.executescript(SCHEMA)
            self._add_missing_columns(connection)
            self._backfill_operation_ids(connection)

    @staticmethod
    def _add_missing_columns(connection: sqlite3.Connection) -> None:
        """Migrate databases created before newer columns were added."""

        migrations: dict[str, dict[str, str]] = {
            "send_jobs": {
                "intro_sent": "ADD COLUMN intro_sent INTEGER NOT NULL DEFAULT 0",
                "intro_operation_id": "ADD COLUMN intro_operation_id TEXT",
                "intro_message_id": "ADD COLUMN intro_message_id TEXT",
            },
            "send_job_files": {
                "attempt_count": "ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0",
                "date_label": "ADD COLUMN date_label TEXT",
                "label_sent": "ADD COLUMN label_sent INTEGER NOT NULL DEFAULT 0",
                "operation_id": "ADD COLUMN operation_id TEXT",
                "message_id": "ADD COLUMN message_id TEXT",
                "label_operation_id": "ADD COLUMN label_operation_id TEXT",
                "label_message_id": "ADD COLUMN label_message_id TEXT",
                "error_code": "ADD COLUMN error_code TEXT",
                "outcome": "ADD COLUMN outcome TEXT",
            },
        }
        for table, columns in migrations.items():
            existing = {
                str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})")
            }
            if not existing:
                continue
            for column, statement in columns.items():
                if column not in existing:
                    connection.execute(f"ALTER TABLE {table} {statement}")

    @staticmethod
    def _backfill_operation_ids(connection: sqlite3.Connection) -> None:
        for job in connection.execute("SELECT id FROM send_jobs").fetchall():
            job_id = str(job["id"])
            connection.execute(
                "UPDATE send_jobs SET intro_operation_id = ? "
                "WHERE id = ? AND intro_operation_id IS NULL",
                (operation_key(job_id, "intro"), job_id),
            )
            previous_label = None
            run_start = 0
            rows = connection.execute(
                "SELECT id, position, date_label FROM send_job_files "
                "WHERE job_id = ? ORDER BY position, id", (job_id,)
            ).fetchall()
            for row in rows:
                position = int(row["position"])
                if row["date_label"] != previous_label:
                    run_start = position
                previous_label = row["date_label"]
                connection.execute(
                    "UPDATE send_job_files SET operation_id = COALESCE(operation_id, ?), "
                    "label_operation_id = COALESCE(label_operation_id, ?) WHERE id = ?",
                    (
                        operation_key(job_id, "document", position),
                        operation_key(job_id, "label", run_start) if previous_label else None,
                        row["id"],
                    ),
                )

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 30000")
        except Exception:
            connection.close()
            raise
        return connection

    def ping(self) -> bool:
        try:
            with closing(self.connect()) as connection:
                connection.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False
