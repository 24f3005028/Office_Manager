"""Shared office tasks. Recurrence advances on completion, never operates BUSY."""

from __future__ import annotations

import calendar
import hashlib
import json
from contextlib import closing
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.db import Database

SCHEMA = """
CREATE TABLE IF NOT EXISTS mobile_tasks (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, notes TEXT NOT NULL,
 due_at TEXT NOT NULL, repeat_rule TEXT NOT NULL, anchor_day INTEGER NOT NULL,
 assignees TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', version INTEGER NOT NULL DEFAULT 1,
 created_by TEXT NOT NULL REFERENCES mobile_users(id), created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL, last_completed_by TEXT, last_completed_at TEXT,
 completed_count INTEGER NOT NULL DEFAULT 0, request_key TEXT NOT NULL,
 payload_hash TEXT NOT NULL, UNIQUE(created_by, request_key));
CREATE TABLE IF NOT EXISTS mobile_task_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES mobile_tasks(id),
 user_id TEXT NOT NULL REFERENCES mobile_users(id), event TEXT NOT NULL,
 version INTEGER NOT NULL, created_at TEXT NOT NULL);
"""


def next_due(due: datetime, rule: str, anchor_day: int, current: datetime) -> datetime:
    """Skip missed occurrences, preserving Indian wall time and monthly anchor day."""
    if rule in {"daily", "weekly"}:
        period = timedelta(days=1 if rule == "daily" else 7)
        return due + period * max(1, (current - due) // period + 1)
    candidate = due
    while True:
        month = candidate.month % 12 + 1
        year = candidate.year + (candidate.month == 12)
        candidate = candidate.replace(
            year=year, month=month, day=min(anchor_day, calendar.monthrange(year, month)[1])
        )
        if candidate > current:
            return candidate


class TaskStore:
    def __init__(self, database: Database):
        self.database = database
        with closing(database.connect()) as db, db:
            db.executescript(SCHEMA)

    def people(self) -> list[dict[str, Any]]:
        with closing(self.database.connect()) as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT id,name FROM mobile_users WHERE active=1 ORDER BY name,id"
                )
            ]

    def rows(self) -> list[dict[str, Any]]:
        with closing(self.database.connect()) as db:
            rows = db.execute(
                "SELECT t.*,u.name AS creator_name,c.name AS completed_by_name FROM mobile_tasks t "
                "JOIN mobile_users u ON u.id=t.created_by "
                "LEFT JOIN mobile_users c ON c.id=t.last_completed_by "
                "WHERE t.status!='cancelled' "
                "ORDER BY (t.status='open') DESC,t.due_at,t.id LIMIT 1000"
            )
            return [{**dict(row), "assignees": json.loads(row["assignees"])} for row in rows]

    def create(self, current: str, payload: dict[str, Any]) -> dict[str, Any]:
        stamp = datetime.now(UTC).isoformat()
        payload = {**payload, "assignees": sorted(set(payload["assignees"]))}
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        due = datetime.fromisoformat(payload["due_at"])
        with closing(self.database.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT * FROM mobile_tasks WHERE created_by=? AND request_key=?",
                (current, payload["request_key"]),
            ).fetchone()
            if old:
                if old["payload_hash"] != fingerprint:
                    raise ValueError("This request code was already used. Refresh before saving.")
                return {**dict(old), "assignees": json.loads(old["assignees"])}
            self._validate_people(db, payload["assignees"])
            if (
                db.execute("SELECT count(*) FROM mobile_tasks WHERE status='open'").fetchone()[0]
                >= 200
            ):
                raise ValueError("The office has 200 open tasks. Complete or cancel some first.")
            task_id = uuid4().hex
            db.execute(
                "INSERT INTO mobile_tasks (id,title,notes,due_at,repeat_rule,anchor_day,assignees,"
                "created_by,created_at,updated_at,request_key,payload_hash) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    task_id,
                    payload["title"],
                    payload["notes"],
                    payload["due_at"],
                    payload["repeat_rule"],
                    due.day,
                    json.dumps(payload["assignees"]),
                    current,
                    stamp,
                    stamp,
                    payload["request_key"],
                    fingerprint,
                ),
            )
            db.execute(
                "INSERT INTO mobile_task_events(task_id,user_id,event,version,created_at) "
                "VALUES (?,?,?,1,?)",
                (task_id, current, "created", stamp),
            )
        return next(row for row in self.rows() if row["id"] == task_id)

    @staticmethod
    def _validate_people(db: Any, people: list[str]) -> None:
        for person in people:
            if not db.execute(
                "SELECT 1 FROM mobile_users WHERE id=? AND active=1", (person,)
            ).fetchone():
                raise ValueError("One of the selected people no longer has office access.")

    def change(
        self,
        task_id: str,
        user: str,
        version: int,
        operation: str,
        *,
        manager: bool = False,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        stamp = datetime.now(UTC)
        with closing(self.database.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM mobile_tasks WHERE id=?", (task_id,)).fetchone()
            if row is None or row["status"] == "cancelled":
                raise ValueError("Task no longer exists. Refresh the list.")
            if row["version"] != version:
                raise ValueError("Someone already changed this task. Refresh before trying again.")
            if operation != "complete" and row["created_by"] != user and not manager:
                raise PermissionError(
                    "Only the task creator or office manager can edit or cancel it."
                )
            if operation == "complete":
                if row["status"] != "open":
                    raise ValueError("This task is already complete.")
                due, status = row["due_at"], "done"
                if row["repeat_rule"] != "none":
                    due = next_due(
                        datetime.fromisoformat(due), row["repeat_rule"], row["anchor_day"], stamp
                    ).isoformat()
                    status = "open"
                db.execute(
                    "UPDATE mobile_tasks SET status=?,due_at=?,last_completed_by=?,"
                    "last_completed_at=?,completed_count=completed_count+1 WHERE id=?",
                    (status, due, user, stamp.isoformat(), task_id),
                )
            elif operation == "cancel":
                db.execute("UPDATE mobile_tasks SET status='cancelled' WHERE id=?", (task_id,))
            elif payload is not None:
                self._validate_people(db, payload["assignees"])
                db.execute(
                    "UPDATE mobile_tasks SET title=?,notes=?,due_at=?,repeat_rule=?,"
                    "anchor_day=?,assignees=? WHERE id=?",
                    (
                        payload["title"],
                        payload["notes"],
                        payload["due_at"],
                        payload["repeat_rule"],
                        datetime.fromisoformat(payload["due_at"]).day,
                        json.dumps(sorted(set(payload["assignees"]))),
                        task_id,
                    ),
                )
            db.execute(
                "UPDATE mobile_tasks SET version=version+1,updated_at=? WHERE id=?",
                (stamp.isoformat(), task_id),
            )
            db.execute(
                "INSERT INTO mobile_task_events(task_id,user_id,event,version,created_at) "
                "VALUES (?,?,?,?,?)",
                (task_id, user, operation, version + 1, stamp.isoformat()),
            )
            updated = db.execute("SELECT * FROM mobile_tasks WHERE id=?", (task_id,)).fetchone()
            return {**dict(updated), "assignees": json.loads(updated["assignees"])}
