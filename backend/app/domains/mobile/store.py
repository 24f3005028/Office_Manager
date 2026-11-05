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
CREATE TABLE IF NOT EXISTS mobile_office_actions (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES mobile_users(id),
 request_key TEXT NOT NULL, kind TEXT NOT NULL, payload_hash TEXT NOT NULL,
 status TEXT NOT NULL, upstream_id TEXT, response TEXT, created_at TEXT NOT NULL,
 UNIQUE(user_id,request_key));
CREATE TABLE IF NOT EXISTS mobile_invite_audit (
 user_id TEXT PRIMARY KEY REFERENCES mobile_users(id),
 created_by TEXT NOT NULL REFERENCES mobile_users(id), created_at TEXT NOT NULL);
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

    def invite(self, name: str, phone: str, *, created_by: str | None = None) -> dict[str, Any]:
        user_id, token = uuid4().hex, secrets.token_urlsafe(32)
        expires = (datetime.now(UTC) + timedelta(minutes=15)).isoformat()
        with closing(self.database.connect()) as db, db:
            db.execute("INSERT INTO mobile_users VALUES (?,?,?,1,?)", (user_id, name, phone, now()))
            db.execute(
                "INSERT INTO mobile_tokens VALUES (?,?,?,?)",
                (digest(token), user_id, "invite", expires),
            )
            if created_by is not None:
                db.execute(
                    "INSERT INTO mobile_invite_audit VALUES (?,?,?)", (user_id, created_by, now())
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

    def pair(self, invite: str, phone: str | None = None) -> dict[str, str] | None:
        token = secrets.token_urlsafe(48)
        expires = (datetime.now(UTC) + timedelta(days=30)).isoformat()
        with closing(self.database.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT t.user_id, u.phone FROM mobile_tokens t JOIN mobile_users u "
                "ON u.id=t.user_id WHERE hash=? AND kind='invite' "
                "AND expires>? AND u.active=1",
                (digest(invite), now()),
            ).fetchone()
            if row is None:
                return None
            if phone is not None and phone != row["phone"]:
                raise ValueError(
                    "This mobile number does not match the invite. "
                    "Check the country code and number with the office."
                )
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
                "INSERT OR IGNORE INTO mobile_parties (id,name) VALUES (?,?)",
                [(digest(name.casefold())[:32], name) for name in names],
            )
            return db.total_changes - before

    def delivery(self, user_id: str, artifact: str) -> tuple[dict[str, Any], bool]:
        with closing(self.database.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM mobile_deliveries WHERE user_id=? AND artifact_key=?",
                (user_id, artifact),
            ).fetchone()
            if row:
                if row["status"] == "not_sent":
                    db.execute(
                        "UPDATE mobile_deliveries SET status='sending', operation_id=?, "
                        "error=NULL WHERE id=?",
                        (f"mobile-{uuid4().hex}", row["id"]),
                    )
                    updated = db.execute(
                        "SELECT * FROM mobile_deliveries WHERE id=?", (row["id"],)
                    ).fetchone()
                    return dict(updated), True
                return dict(row), False
            delivery_id = uuid4().hex
            db.execute(
                "INSERT INTO mobile_deliveries "
                "(id,user_id,artifact_key,operation_id,status,created_at) "
                "VALUES (?,?,?,?,'sending',?)",
                (delivery_id, user_id, artifact, f"mobile-{delivery_id}", now()),
            )
            return dict(
                db.execute("SELECT * FROM mobile_deliveries WHERE id=?", (delivery_id,)).fetchone()
            ), True

    def finish_delivery(
        self, delivery_id: str, status: str, message_id: str | None = None, error: str | None = None
    ) -> dict[str, Any]:
        with closing(self.database.connect()) as db, db:
            db.execute(
                "UPDATE mobile_deliveries SET status=?,message_id=?,error=? WHERE id=?",
                (status, message_id, error, delivery_id),
            )
            return dict(
                db.execute("SELECT * FROM mobile_deliveries WHERE id=?", (delivery_id,)).fetchone()
            )

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

    def cleanup_candidates(self) -> list[dict[str, Any]]:
        with closing(self.database.connect()) as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT id,status,finished_at FROM mobile_jobs "
                    "WHERE status IN ('ready','failed','cancelled')"
                )
            ]

    def reserve_office_action(
        self, user_id: str, key: str, kind: str, payload: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        fingerprint = digest(json.dumps(payload, sort_keys=True))
        with closing(self.database.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM mobile_office_actions WHERE user_id=? AND request_key=?",
                (user_id, key),
            ).fetchone()
            if row:
                if row["kind"] != kind or row["payload_hash"] != fingerprint:
                    raise ValueError("This request was already used for a different action.")
                return dict(row), False
            action_id = uuid4().hex
            db.execute(
                "INSERT INTO mobile_office_actions "
                "(id,user_id,request_key,kind,payload_hash,status,created_at) "
                "VALUES (?,?,?,?,?,'submitting',?)",
                (action_id, user_id, key, kind, fingerprint, now()),
            )
            return dict(
                db.execute(
                    "SELECT * FROM mobile_office_actions WHERE id=?", (action_id,)
                ).fetchone()
            ), True

    def finish_office_action(
        self, action_id: str, status: str, upstream_id: str | None, response: dict[str, Any]
    ) -> None:
        with closing(self.database.connect()) as db, db:
            db.execute(
                "UPDATE mobile_office_actions SET status=?,upstream_id=?,response=? WHERE id=?",
                (status, upstream_id, json.dumps(response), action_id),
            )

    def office_action(self, action_id: str, user_id: str) -> dict[str, Any] | None:
        with closing(self.database.connect()) as db:
            row = db.execute(
                "SELECT * FROM mobile_office_actions WHERE id=? AND user_id=?",
                (action_id, user_id),
            ).fetchone()
            return dict(row) if row else None

    def office_actions(self, user_id: str) -> list[dict[str, Any]]:
        with closing(self.database.connect()) as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM mobile_office_actions WHERE user_id=? "
                    "ORDER BY created_at DESC LIMIT 30",
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
                "UPDATE mobile_office_actions SET status='needs_review',response=? "
                "WHERE status='submitting'",
                (
                    json.dumps(
                        {
                            "error": "Office restarted before confirming this action. "
                            "Check the dashboard before retrying."
                        }
                    ),
                ),
            )
            db.execute(
                "UPDATE mobile_jobs SET status='failed',error=?,finished_at=? "
                "WHERE status IN ('queued','warning','generating')",
                ("Office service restarted. Request the report again.", now()),
            )
            db.execute(
                "UPDATE mobile_deliveries SET status='needs_review',error=? WHERE status='sending'",
                ("Service restarted. Check WhatsApp first.",),
            )
