"""Durable mobile accounts, hashed pairing/session tokens, jobs and deliveries."""

from __future__ import annotations

import hashlib
import json
import secrets
from contextlib import closing
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.db import Database

SCHEMA = """
CREATE TABLE IF NOT EXISTS mobile_users (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mobile_tokens (
 hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES mobile_users(id), kind TEXT NOT NULL,
 expires TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mobile_parties (
 id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS mobile_jobs (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES mobile_users(id), request_key TEXT NOT NULL,
 party_id TEXT NOT NULL, party_name TEXT NOT NULL, as_of TEXT NOT NULL,
 status TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL, finished_at TEXT,
 pdf_path TEXT, pdf_hash TEXT, details TEXT,
 UNIQUE(user_id, request_key));
CREATE UNIQUE INDEX IF NOT EXISTS mobile_one_pending_per_user ON mobile_jobs(user_id)
 WHERE status IN ('queued','warning','generating');
CREATE TABLE IF NOT EXISTS mobile_deliveries (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES mobile_users(id), artifact_key TEXT NOT NULL,
 operation_id TEXT NOT NULL UNIQUE, status TEXT NOT NULL, message_id TEXT, error TEXT,
 created_at TEXT NOT NULL, UNIQUE(user_id, artifact_key));
"""


def now() -> str:
    return datetime.now(UTC).isoformat()


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class MobileStore:
    def __init__(self, database: Database) -> None:
        self.database = database
        with closing(database.connect()) as db, db:
            db.executescript(SCHEMA)

    def users(self) -> list[dict[str, Any]]:
        with closing(self.database.connect()) as db:
            return [
                dict(row) for row in db.execute("SELECT * FROM mobile_users ORDER BY created_at")
            ]

    def invite(self, name: str, phone: str) -> dict[str, Any]:
        user_id, token = uuid4().hex, secrets.token_urlsafe(32)
        expires = (datetime.now(UTC) + timedelta(minutes=15)).isoformat()
        with closing(self.database.connect()) as db, db:
            db.execute("INSERT INTO mobile_users VALUES (?,?,?,1,?)", (user_id, name, phone, now()))
            db.execute(
                "INSERT INTO mobile_tokens VALUES (?,?,?,?)",
                (digest(token), user_id, "invite", expires),
            )
        return {"id": user_id, "invite_code": token, "expires_at": expires}

    def revoke(self, user_id: str) -> None:
        with closing(self.database.connect()) as db, db:
            db.execute("UPDATE mobile_users SET active=0 WHERE id=?", (user_id,))
            db.execute("DELETE FROM mobile_tokens WHERE user_id=?", (user_id,))
            db.execute(
                "UPDATE mobile_jobs SET status='cancelled', error=? "
                "WHERE user_id=? AND status='queued'",
                ("Access revoked.", user_id),
            )

    def pair(self, invite: str) -> dict[str, str] | None:
        token = secrets.token_urlsafe(48)
        expires = (datetime.now(UTC) + timedelta(days=30)).isoformat()
        with closing(self.database.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT t.user_id FROM mobile_tokens t JOIN mobile_users u "
                "ON u.id=t.user_id WHERE hash=? AND kind='invite' "
                "AND expires>? AND u.active=1",
                (digest(invite), now()),
            ).fetchone()
            if row is None:
                return None
            db.execute("DELETE FROM mobile_tokens WHERE hash=?", (digest(invite),))
            db.execute(
                "INSERT INTO mobile_tokens VALUES (?,?,?,?)",
                (digest(token), row["user_id"], "session", expires),
            )
        return {"token": token, "expires_at": expires}

    def authenticate(self, token: str) -> dict[str, Any] | None:
        with closing(self.database.connect()) as db:
            row = db.execute(
                "SELECT u.* FROM mobile_tokens t JOIN mobile_users u ON u.id=t.user_id "
                "WHERE t.hash=? AND t.kind='session' AND t.expires>? AND u.active=1",
                (digest(token), now()),
            ).fetchone()
            return dict(row) if row else None

    def logout(self, token: str) -> None:
        with closing(self.database.connect()) as db, db:
            db.execute("DELETE FROM mobile_tokens WHERE hash=?", (digest(token),))

    def active(self, user_id: str) -> bool:
        with closing(self.database.connect()) as db:
            return (
                db.execute(
                    "SELECT 1 FROM mobile_users WHERE id=? AND active=1", (user_id,)
                ).fetchone()
                is not None
            )

    def add_parties(self, names: list[str]) -> int:
        with closing(self.database.connect()) as db, db:
            before = db.total_changes
            db.executemany(
                "INSERT OR IGNORE INTO mobile_parties VALUES (?,?)",
                [(digest(name.casefold())[:32], name) for name in names],
            )
            return db.total_changes - before

    def parties(self, query: str = "") -> list[dict[str, str]]:
        with closing(self.database.connect()) as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM mobile_parties WHERE instr(lower(name),lower(?))>0 "
                    "ORDER BY name LIMIT 100",
                    (query,),
                )
            ]

    def party(self, party_id: str) -> dict[str, str] | None:
        with closing(self.database.connect()) as db:
            row = db.execute("SELECT * FROM mobile_parties WHERE id=?", (party_id,)).fetchone()
            return dict(row) if row else None

    def create_job(
        self, user_id: str, party: dict[str, str], as_of: str, request_key: str
    ) -> tuple[dict[str, Any], bool]:
        with closing(self.database.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM mobile_jobs WHERE user_id=? AND request_key=?",
                (user_id, request_key),
            ).fetchone()
            if existing:
                if existing["party_id"] != party["id"] or existing["as_of"] != as_of:
                    raise ValueError(
                        "This request ID was already used for different report details."
                    )
                return self.public(dict(existing)), False
            if db.execute(
                "SELECT 1 FROM mobile_jobs WHERE user_id=? AND "
                "status IN ('queued','warning','generating')",
                (user_id,),
            ).fetchone():
                raise ValueError("Your previous report is still being prepared.")
            job_id = uuid4().hex
            db.execute(
                "INSERT INTO mobile_jobs "
                "(id,user_id,request_key,party_id,party_name,as_of,status,created_at) "
                "VALUES (?,?,?,?,?,?,'queued',?)",
                (job_id, user_id, request_key, party["id"], party["name"], as_of, now()),
            )
            row = db.execute("SELECT * FROM mobile_jobs WHERE id=?", (job_id,)).fetchone()
            return self.public(dict(row)), True

    @staticmethod
    def public(row: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in row.items()
            if key not in {"pdf_path", "pdf_hash", "request_key"}
        } | {"details": json.loads(row["details"]) if row.get("details") else None}

    def job(self, job_id: str, user_id: str | None = None) -> dict[str, Any] | None:
        with closing(self.database.connect()) as db:
            row = db.execute("SELECT * FROM mobile_jobs WHERE id=?", (job_id,)).fetchone()
            if row is None or (user_id is not None and row["user_id"] != user_id):
                return None
            return dict(row)

    def jobs(self, user_id: str) -> list[dict[str, Any]]:
        with closing(self.database.connect()) as db:
            return [
                self.public(dict(row))
                for row in db.execute(
                    "SELECT * FROM mobile_jobs WHERE user_id=? ORDER BY created_at DESC LIMIT 30",
                    (user_id,),
                )
            ]

    def update_job(self, job_id: str, **values: Any) -> None:
        allowed = {"status", "error", "finished_at", "pdf_path", "pdf_hash", "details"}
        if not values or set(values) - allowed:
            raise ValueError("Invalid report update")
        assignments = ",".join(f"{key}=?" for key in values)
        with closing(self.database.connect()) as db, db:
            db.execute(
                f"UPDATE mobile_jobs SET {assignments} WHERE id=?", (*values.values(), job_id)
            )

    def recover(self) -> None:
        with closing(self.database.connect()) as db, db:
            db.execute(
                "UPDATE mobile_jobs SET status='failed',error=?,finished_at=? "
                "WHERE status IN ('queued','warning','generating')",
                ("Office service restarted. Request the report again.", now()),
            )
            db.execute(
                "UPDATE mobile_deliveries SET status='needs_review',error=? WHERE status='sending'",
                ("Service restarted. Check WhatsApp first.",),
            )
