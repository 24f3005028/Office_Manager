"""SQLite repository for durable send jobs and per-file status."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime

from app.db import Database
from app.domains.send_jobs.models import (
    ClaimedFile,
    JobFileInput,
    JobFileRecord,
    SendJobRecord,
    operation_key,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SendJobRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def recover_incomplete(self) -> None:
        """An interrupted operation may have sent; never automatically replay it."""

        connection = self.database.connect()
        try:
            with connection:
                connection.execute(
                    "UPDATE send_job_files SET status = 'unknown', outcome = 'unknown', "
                    "error_code = 'INTERRUPTED_SEND', error = ? WHERE status = 'sending'",
                    ("Send interrupted before its receipt was saved; review before sending again",),
                )
                jobs = connection.execute(
                    "SELECT DISTINCT job_id FROM send_job_files WHERE status = 'unknown'"
                ).fetchall()
                for job in jobs:
                    self._finalize_job(connection, str(job["job_id"]))
                connection.execute(
                    "UPDATE send_jobs SET status = 'queued' "
                    "WHERE status = 'running' AND cancel_requested = 0"
                )
                self._cancel_queued_jobs(connection)
                for job in connection.execute(
                    "SELECT id FROM send_jobs WHERE status IN ('queued', 'running')"
                ).fetchall():
                    self._finalize_job(connection, str(job["id"]))
        finally:
            connection.close()

    def create(
        self,
        job_id: str,
        recipient: str,
        message: str | None,
        files: list[JobFileInput],
    ) -> SendJobRecord:
        created_at = _now()
        rows = []
        previous_label = None
        run_start = 0
        for item in files:
            if item.date_label != previous_label:
                run_start = item.position
            previous_label = item.date_label
            rows.append((
                job_id, item.file_id, item.category, str(item.path), item.file_name,
                item.position, item.date_label, operation_key(job_id, "document", item.position),
                operation_key(job_id, "label", run_start) if item.date_label else None, created_at,
            ))
        connection = self.database.connect()
        try:
            with connection:
                connection.execute(
                    "INSERT INTO send_jobs "
                    "(id, recipient, message, status, created_at, intro_operation_id) "
                    "VALUES (?, ?, ?, 'queued', ?, ?)",
                    (job_id, recipient, message, created_at, operation_key(job_id, "intro")),
                )
                connection.executemany(
                    "INSERT INTO send_job_files "
                    "(job_id, file_id, category, file_path, file_name, position, date_label, "
                    "operation_id, label_operation_id, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?)",
                    rows,
                )
        finally:
            connection.close()
        result = self.get(job_id)
        if result is None:
            raise RuntimeError("Created send job could not be read back")
        return result

    def list(self, limit: int = 100) -> list[SendJobRecord]:
        connection = self.database.connect()
        try:
            rows = connection.execute(
                "SELECT id FROM send_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        finally:
            connection.close()
        return [job for row in rows if (job := self.get(str(row["id"]))) is not None]

    def get(self, job_id: str) -> SendJobRecord | None:
        connection = self.database.connect()
        try:
            job_row = connection.execute(
                "SELECT * FROM send_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if job_row is None:
                return None
            file_rows = connection.execute(
                "SELECT * FROM send_job_files WHERE job_id = ? ORDER BY position, id", (job_id,)
            ).fetchall()
        finally:
            connection.close()
        return self._to_record(job_row, file_rows)

    def cancel(self, job_id: str) -> SendJobRecord | None:
        connection = self.database.connect()
        try:
            with connection:
                row = connection.execute(
                    "SELECT status FROM send_jobs WHERE id = ?", (job_id,)
                ).fetchone()
                if row is None:
                    return None
                if row["status"] in {"queued", "running", "needs_review"}:
                    connection.execute(
                        "UPDATE send_jobs SET cancel_requested = 1 WHERE id = ?", (job_id,)
                    )
                    connection.execute(
                        "UPDATE send_job_files SET status = 'cancelled' "
                        "WHERE job_id = ? AND status = 'queued'",
                        (job_id,),
                    )
                    self._finalize_job(connection, job_id)
        finally:
            connection.close()
        return self.get(job_id)

    def claim_next_file(self) -> ClaimedFile | None:
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._cancel_queued_jobs(connection)
            row = connection.execute(
                "SELECT jf.*, j.recipient, j.message, j.intro_operation_id, j.status AS job_status "
                "FROM send_job_files jf JOIN send_jobs j ON j.id = jf.job_id "
                "WHERE jf.status = 'queued' AND j.status IN ('queued', 'running') "
                "AND j.cancel_requested = 0 "
                "AND NOT EXISTS (SELECT 1 FROM send_job_files busy "
                "WHERE busy.job_id = j.id AND busy.status IN ('sending', 'unknown')) "
                "ORDER BY j.created_at, jf.position, jf.id LIMIT 1"
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            if row["job_status"] == "queued":
                connection.execute(
                    "UPDATE send_jobs SET status = 'running', "
                    "started_at = COALESCE(started_at, ?) WHERE id = ?",
                    (_now(), row["job_id"]),
                )
            connection.execute(
                "UPDATE send_job_files SET status = 'sending' WHERE id = ?", (row["id"],)
            )
            connection.commit()
            return ClaimedFile(
                job_id=str(row["job_id"]),
                recipient=str(row["recipient"]),
                message=row["message"],
                file_row_id=int(row["id"]),
                file_id=str(row["file_id"]),
                category=str(row["category"]),
                path=str(row["file_path"]),
                file_name=str(row["file_name"]),
                position=int(row["position"]),
                date_label=row["date_label"],
                label_sent=bool(row["label_sent"]),
                attempt_count=int(row["attempt_count"]),
                operation_id=str(row["operation_id"]),
                intro_operation_id=str(row["intro_operation_id"]),
                label_operation_id=row["label_operation_id"],
            )
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def requeue_file(self, job_id: str, file_row_id: int, attempt_count: int) -> None:
        """Return a claimed file to the queue for another attempt."""

        connection = self.database.connect()
        try:
            with connection:
                connection.execute(
                    "UPDATE send_job_files SET status = CASE WHEN "
                    "(SELECT cancel_requested FROM send_jobs WHERE id = ?) = 1 "
                    "THEN 'cancelled' ELSE 'queued' END, attempt_count = ?, error = NULL, "
                    "error_code = NULL, outcome = NULL "
                    "WHERE id = ? AND job_id = ? AND status = 'sending'",
                    (job_id, attempt_count, file_row_id, job_id),
                )
                self._finalize_job(connection, job_id)
        finally:
            connection.close()

    def is_intro_sent(self, job_id: str) -> bool:
        connection = self.database.connect()
        try:
            row = connection.execute(
                "SELECT intro_sent FROM send_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        finally:
            connection.close()
        return bool(row and row["intro_sent"])

    def mark_intro_sent(self, job_id: str, message_id: str) -> None:
        """Only a valid send receipt acknowledges the opening message."""

        connection = self.database.connect()
        try:
            with connection:
                connection.execute(
                    "UPDATE send_jobs SET intro_sent = 1, intro_message_id = ? WHERE id = ?",
                    (message_id, job_id),
                )
        finally:
            connection.close()

    def mark_label_sent(self, job_id: str, file_row_id: int, message_id: str) -> None:
        connection = self.database.connect()
        try:
            with connection:
                connection.execute(
                    "UPDATE send_job_files SET label_sent = 1, label_message_id = ? "
                    "WHERE id = ? AND job_id = ?",
                    (message_id, file_row_id, job_id),
                )
        finally:
            connection.close()

    def is_label_already_sent(self, job_id: str, operation_id: str) -> bool:
        """Only the same contiguous date run shares a label acknowledgment."""

        connection = self.database.connect()
        try:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM send_job_files "
                "WHERE job_id = ? AND label_operation_id = ? AND label_sent = 1",
                (job_id, operation_id),
            ).fetchone()
        finally:
            connection.close()
        return bool(row and row["count"])

    def is_cancel_requested(self, job_id: str) -> bool:
        connection = self.database.connect()
        try:
            row = connection.execute(
                "SELECT cancel_requested FROM send_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        finally:
            connection.close()
        return bool(row and row["cancel_requested"])

    def mark_file_result(
        self,
        job_id: str,
        file_row_id: int,
        status: str,
        error: str | None = None,
        *,
        message_id: str | None = None,
        error_code: str | None = None,
        outcome: str | None = None,
        attempt_count: int | None = None,
    ) -> None:
        if status not in {"sent", "failed", "cancelled", "unknown"}:
            raise ValueError(f"Invalid final file status: {status}")
        connection = self.database.connect()
        try:
            with connection:
                connection.execute(
                    "UPDATE send_job_files SET status = ?, error = ?, sent_at = ?, "
                    "message_id = ?, error_code = ?, outcome = ?, "
                    "attempt_count = COALESCE(?, attempt_count) WHERE id = ? AND job_id = ?",
                    (status, error, _now() if status == "sent" else None, message_id,
                     error_code, outcome, attempt_count, file_row_id, job_id),
                )
                self._finalize_job(connection, job_id)
        finally:
            connection.close()

    def _cancel_queued_jobs(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            "UPDATE send_job_files SET status = 'cancelled' "
            "WHERE status = 'queued' AND job_id IN "
            "(SELECT id FROM send_jobs WHERE cancel_requested = 1)",
        )
        rows = connection.execute(
            "SELECT id FROM send_jobs WHERE cancel_requested = 1 "
            "AND status IN ('queued', 'running')"
        ).fetchall()
        for row in rows:
            self._finalize_job(connection, str(row["id"]))

    def _finalize_job(self, connection: sqlite3.Connection, job_id: str) -> None:
        job = connection.execute(
            "SELECT cancel_requested, status FROM send_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if job is None:
            return
        unknown = connection.execute(
            "SELECT error FROM send_job_files WHERE job_id = ? AND status = 'unknown' "
            "ORDER BY position LIMIT 1", (job_id,)
        ).fetchone()
        if unknown is not None:
            connection.execute(
                "UPDATE send_jobs SET status = 'needs_review', error = ?, finished_at = NULL "
                "WHERE id = ?", (unknown["error"], job_id)
            )
            return
        if job["status"] in {"completed", "failed", "cancelled"}:
            return
        active = connection.execute(
            "SELECT COUNT(*) AS count FROM send_job_files "
            "WHERE job_id = ? AND status IN ('queued', 'sending')",
            (job_id,),
        ).fetchone()["count"]
        if active:
            return
        if job["cancel_requested"]:
            final_status = "cancelled"
        else:
            failed = connection.execute(
                "SELECT COUNT(*) AS count FROM send_job_files "
                "WHERE job_id = ? AND status = 'failed'",
                (job_id,),
            ).fetchone()["count"]
            final_status = "failed" if failed else "completed"
        error_summary = None
        if final_status == "failed":
            error_summary = self._build_error_summary(connection, job_id)
        connection.execute(
            "UPDATE send_jobs SET status = ?, finished_at = ?, error = ? WHERE id = ?",
            (final_status, _now(), error_summary, job_id),
        )

    @staticmethod
    def _build_error_summary(
        connection: sqlite3.Connection, job_id: str
    ) -> str | None:
        """Summarize per-file failures for the API/UI, with the first real reason."""

        total = connection.execute(
            "SELECT COUNT(*) AS count FROM send_job_files WHERE job_id = ?", (job_id,)
        ).fetchone()["count"]
        failed = connection.execute(
            "SELECT COUNT(*) AS count FROM send_job_files "
            "WHERE job_id = ? AND status = 'failed' AND error IS NOT NULL",
            (job_id,),
        ).fetchone()
        failed_count = failed["count"]
        if not failed_count:
            return "Sending failed"
        prefix = (
            f"{failed_count} of {total} documents failed"
            if total > 1
            else "The document failed to send"
        )
        first_error_row = connection.execute(
            "SELECT error FROM send_job_files WHERE job_id = ? "
            "AND status = 'failed' AND error IS NOT NULL ORDER BY position LIMIT 1",
            (job_id,),
        ).fetchone()
        first_error = str(first_error_row["error"]).strip() if first_error_row else ""
        return f"{prefix}: {first_error}" if first_error else prefix

    @staticmethod
    def _to_record(
        job_row: sqlite3.Row, file_rows: Sequence[sqlite3.Row]
    ) -> SendJobRecord:
        files = tuple(
            JobFileRecord(
                row_id=int(row["id"]),
                file_id=str(row["file_id"]),
                category=str(row["category"]),
                path=str(row["file_path"]),
                file_name=str(row["file_name"]),
                position=int(row["position"]),
                date_label=row["date_label"],
                status=str(row["status"]),
                error=row["error"],
                sent_at=row["sent_at"],
                operation_id=str(row["operation_id"]),
                message_id=row["message_id"],
                label_operation_id=row["label_operation_id"],
                label_message_id=row["label_message_id"],
                attempt_count=int(row["attempt_count"]),
                error_code=row["error_code"],
                outcome=row["outcome"],
            )
            for row in file_rows
        )
        return SendJobRecord(
            job_id=str(job_row["id"]),
            recipient=str(job_row["recipient"]),
            message=job_row["message"],
            status=str(job_row["status"]),
            cancel_requested=bool(job_row["cancel_requested"]),
            created_at=str(job_row["created_at"]),
            started_at=job_row["started_at"],
            finished_at=job_row["finished_at"],
            error=job_row["error"],
            files=files,
            intro_sent=bool(job_row["intro_sent"]),
            intro_operation_id=str(job_row["intro_operation_id"]),
            intro_message_id=job_row["intro_message_id"],
        )
