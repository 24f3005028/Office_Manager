"""Manual-run journal, including a cross-process active-run constraint."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime
from typing import Any

from app.db import Database
from app.domains.pouncha_sync.parser import SyncError


class RunRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def recover(self) -> None:
        with closing(self.database.connect()) as connection, connection:
            rows = connection.execute(
                "SELECT payload FROM pouncha_manual_runs WHERE status IN ('queued', 'running')"
            ).fetchall()
            for row in rows:
                run = json.loads(row[0])
                uncertain = run["stage"] in ("appending", "verifying")
                run.update(
                    status="needs_review" if uncertain else "failed",
                    error="Backend restarted during this run. No automatic resume was attempted.",
                )
                connection.execute(
                    "UPDATE pouncha_manual_runs SET status=?, payload=? WHERE id=?",
                    (run["status"], json.dumps(run), run["run_id"]),
                )

    def create(self, source: str, preview: bool, start: str | None, end: str) -> dict[str, Any]:
        run = dict(
            run_id=uuid.uuid4().hex,
            status="queued",
            stage="preparing",
            source=source,
            preview_only=preview,
            start_date=start,
            end_date=end,
            created_at=datetime.now(UTC).isoformat(),
            finished_at=None,
            exported_count=0,
            existing_count=0,
            appended_count=0,
            new_count=0,
            conflicts=[],
            warnings=[],
            preview=[],
            error=None,
            updated_range=None,
            intended_rows=[],
        )
        try:
            with closing(self.database.connect()) as connection, connection:
                connection.execute(
                    "INSERT INTO pouncha_manual_runs(id,status,payload) VALUES (?,?,?)",
                    (run["run_id"], run["status"], json.dumps(run)),
                )
        except sqlite3.IntegrityError as exc:
            raise SyncError(
                "A sync is active or needs review. Resolve it before starting another."
            ) from exc
        return self.public(run)

    def get(self, run_id: str) -> dict[str, Any] | None:
        with closing(self.database.connect()) as connection:
            row = connection.execute(
                "SELECT payload FROM pouncha_manual_runs WHERE id=?",
                (run_id,),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def update(self, run_id: str, **changes: Any) -> None:
        run = self.get(run_id)
        if run is None:
            raise SyncError("Sync run not found.")
        run.update(changes)
        with closing(self.database.connect()) as connection, connection:
            connection.execute(
                "UPDATE pouncha_manual_runs SET status=?,payload=? WHERE id=?",
                (run["status"], json.dumps(run), run_id),
            )

    def recent(self) -> list[dict[str, Any]]:
        with closing(self.database.connect()) as connection:
            rows = connection.execute(
                "SELECT payload FROM pouncha_manual_runs ORDER BY rowid DESC LIMIT 20"
            ).fetchall()
        return [self.public(json.loads(row[0])) for row in rows]

    @staticmethod
    def public(run: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in run.items() if key != "intended_rows"}
