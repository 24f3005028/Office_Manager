"""Removing desktop automation must leave the sender and existing data usable."""

import sqlite3
from pathlib import Path

from app.config import Settings
from app.db import Database
from app.main import create_app
from fastapi.testclient import TestClient

from tests.fakes import FakeBridge


def test_sender_starts_without_automation_services(tmp_path: Path) -> None:
    settings = Settings(
        database_path=tmp_path / "dashboard.sqlite3",
        bills_roots="",
        credit_notes_roots="",
        debit_notes_roots="",
    )
    app = create_app(settings, FakeBridge(), start_worker=False)
    with TestClient(app) as client:
        assert client.get("/api/health").json()["database"] == "ok"
        assert client.get("/api/send-jobs").json() == []
        assert client.get("/api/busy-ledger/status").status_code == 200
        assert "/api/pouncha-sync/run" in client.get("/openapi.json").json()["paths"]
        assert app.state.pouncha_service.repository.recent() == []
        assert not hasattr(app.state, "pouncha_scheduler")
        assert not hasattr(app.state, "pouncha_sync_service")


def test_fresh_database_does_not_create_automation_tables(tmp_path: Path) -> None:
    database = Database(tmp_path / "new.sqlite3")
    database.initialize()
    with sqlite3.connect(database.path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    assert "send_jobs" in tables
    assert "pouncha_sync_runs" not in tables


def test_existing_automation_history_is_preserved(tmp_path: Path) -> None:
    database = Database(tmp_path / "existing.sqlite3")
    with sqlite3.connect(database.path) as connection:
        connection.execute("CREATE TABLE pouncha_sync_runs (run_id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO pouncha_sync_runs VALUES ('historical-run')")
    database.initialize()
    with sqlite3.connect(database.path) as connection:
        assert connection.execute("SELECT run_id FROM pouncha_sync_runs").fetchone() == (
            "historical-run",
        )
