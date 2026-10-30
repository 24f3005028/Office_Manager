"""SQLite audit repository for Pouncha sync runs."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from datetime import UTC, date, datetime

from app.db import Database
from app.domains.pouncha_sync.models import PounchaRunStatus, PounchaSyncRun


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _row_to_run(row: sqlite3.Row) -> PounchaSyncRun:
    raw_warnings = row["warnings"]
    warnings: tuple[str, ...] = ()
    if raw_warnings:
        try:
            decoded = json.loads(raw_warnings)
        except (TypeError, ValueError):
            decoded = []
        if isinstance(decoded, list):
            warnings = tuple(str(item) for item in decoded)
    return PounchaSyncRun(
        run_id=str(row["run_id"]),
        trigger_type=str(row["trigger_type"]),
        start_date=_parse_date(str(row["start_date"])),
        end_date=_parse_date(str(row["end_date"])),
        exported_sale_count=int(row["exported_sale_count"]),
        already_in_sheet_count=int(row["already_in_sheet_count"]),
        appended_count=int(row["appended_count"]),
        status=str(row["status"]),
        error_message=(
            str(row["error_message"]) if row["error_message"] is not None else None
        ),
        warnings=warnings,
        started_at=_parse_datetime(row["started_at"]),
        completed_at=_parse_datetime(row["completed_at"]),
    )


class PounchaSyncRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_run(
        self,
        *,
        run_id: str,
        trigger_type: str,
        start_date: date,
        end_date: date,
        started_at: datetime | None = None,
    ) -> PounchaSyncRun:
        moment = started_at or datetime.now(UTC)
        with closing(self.database.connect()) as connection, connection:
            connection.execute(
                "INSERT INTO pouncha_sync_runs "
                "(run_id, trigger_type, start_date, end_date, status, started_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    trigger_type,
                    start_date.isoformat(),
                    end_date.isoformat(),
                    PounchaRunStatus.QUEUED.value,
                    _iso(moment),
                ),
            )
        return PounchaSyncRun(
            run_id=run_id,
            trigger_type=trigger_type,
            start_date=start_date,
            end_date=end_date,
            exported_sale_count=0,
            already_in_sheet_count=0,
            appended_count=0,
            status=PounchaRunStatus.QUEUED.value,
            error_message=None,
            started_at=moment,
        )

    def mark_running(
        self, run_id: str, *, started_at: datetime | None = None
    ) -> None:
        with closing(self.database.connect()) as connection, connection:
            connection.execute(
                "UPDATE pouncha_sync_runs SET status = ?, started_at = ? "
                "WHERE run_id = ?",
                (
                    PounchaRunStatus.RUNNING.value,
                    _iso(started_at or datetime.now(UTC)),
                    run_id,
                ),
            )

    def complete_run(
        self,
        run_id: str,
        *,
        status: str,
        exported_sale_count: int = 0,
        already_in_sheet_count: int = 0,
        appended_count: int = 0,
        error_message: str | None = None,
        warnings: Sequence[str] = (),
        completed_at: datetime | None = None,
    ) -> None:
        with closing(self.database.connect()) as connection, connection:
            connection.execute(
                "UPDATE pouncha_sync_runs SET status = ?, "
                "exported_sale_count = ?, already_in_sheet_count = ?, "
                "appended_count = ?, error_message = ?, warnings = ?, "
                "completed_at = ? WHERE run_id = ?",
                (
                    status,
                    exported_sale_count,
                    already_in_sheet_count,
                    appended_count,
                    error_message,
                    json.dumps(list(warnings)) if warnings else None,
                    _iso(completed_at or datetime.now(UTC)),
                    run_id,
                ),
            )

    def get_run(self, run_id: str) -> PounchaSyncRun | None:
        with closing(self.database.connect()) as connection:
            row = connection.execute(
                "SELECT * FROM pouncha_sync_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return _row_to_run(row) if row is not None else None

    def list_runs(self, limit: int = 10) -> list[PounchaSyncRun]:
        safe_limit = max(1, min(int(limit), 200))
        with closing(self.database.connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM pouncha_sync_runs "
                "ORDER BY started_at DESC, run_id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [_row_to_run(row) for row in rows]

    def last_run(self) -> PounchaSyncRun | None:
        runs = self.list_runs(limit=1)
        return runs[0] if runs else None

    def last_success(self) -> PounchaSyncRun | None:
        with closing(self.database.connect()) as connection:
            row = connection.execute(
                "SELECT * FROM pouncha_sync_runs WHERE status = ? "
                "AND completed_at IS NOT NULL "
                "ORDER BY completed_at DESC LIMIT 1",
                (PounchaRunStatus.SUCCESS.value,),
            ).fetchone()
        return _row_to_run(row) if row is not None else None

    def active_run(self) -> PounchaSyncRun | None:
        with closing(self.database.connect()) as connection:
            row = connection.execute(
                "SELECT * FROM pouncha_sync_runs WHERE status IN (?, ?) "
                "ORDER BY started_at DESC LIMIT 1",
                (PounchaRunStatus.QUEUED.value, PounchaRunStatus.RUNNING.value),
            ).fetchone()
        return _row_to_run(row) if row is not None else None

    def last_successful_since(self, moment: datetime) -> PounchaSyncRun | None:
        with closing(self.database.connect()) as connection:
            row = connection.execute(
                "SELECT * FROM pouncha_sync_runs WHERE status = ? "
                "AND completed_at IS NOT NULL AND completed_at >= ? "
                "ORDER BY completed_at DESC LIMIT 1",
                (PounchaRunStatus.SUCCESS.value, _iso(moment)),
            ).fetchone()
        return _row_to_run(row) if row is not None else None

    def mark_stale_runs_failed(
        self, *, completed_at: datetime | None = None
    ) -> int:
        moment = _iso(completed_at or datetime.now(UTC))
        with closing(self.database.connect()) as connection, connection:
            cursor = connection.execute(
                "UPDATE pouncha_sync_runs SET status = ?, error_message = ?, "
                "completed_at = ? WHERE status IN (?, ?)",
                (
                    PounchaRunStatus.FAILED.value,
                    "Interrupted by a backend restart.",
                    moment,
                    PounchaRunStatus.QUEUED.value,
                    PounchaRunStatus.RUNNING.value,
                ),
            )
        return int(cursor.rowcount or 0)
