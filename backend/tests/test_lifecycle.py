import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from app.config import Settings
from app.db import Database
from app.main import create_app
from fastapi.testclient import TestClient

from tests.fakes import FakeBridge


def test_import_and_factory_do_not_load_runtime_settings_or_open_a_database(tmp_path: Path) -> None:
    code = """
import sqlite3
import app.config
def forbidden(*args, **kwargs):
    raise AssertionError('Import must not initialize runtime settings or SQLite')
sqlite3.connect = forbidden
app.config.Settings = forbidden
from app.main import app, create_app
from fastapi import FastAPI
assert isinstance(app, FastAPI)
assert isinstance(create_app(), FastAPI)
assert not hasattr(app.state, 'database')
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "DATABASE_PATH": str(tmp_path / "must-not-exist.sqlite3")},
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "must-not-exist.sqlite3").exists()


def test_lifespan_initializes_temp_database_and_closes_bridge(tmp_path: Path) -> None:
    database_path = tmp_path / "lifespan.sqlite3"
    bridge = FakeBridge()
    settings = Settings(
        database_path=database_path, bills_roots="", credit_notes_roots="",
        debit_notes_roots="", cors_origins="http://fixture-ui",
    )
    app = create_app(settings, bridge, start_worker=False)
    assert not database_path.exists()
    with TestClient(app) as client:
        assert database_path.exists()
        response = client.get("/api/health", headers={"Origin": "http://fixture-ui"})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://fixture-ui"
        assert not bridge.closed
    assert bridge.closed


def test_database_initialize_and_ping_close_connections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Database(tmp_path / "connections.sqlite3")
    original_connect = database.connect
    connections: list[sqlite3.Connection] = []

    def tracked_connect() -> sqlite3.Connection:
        connection = original_connect()
        connections.append(connection)
        return connection

    monkeypatch.setattr(database, "connect", tracked_connect)
    database.initialize()
    assert database.ping()
    assert len(connections) == 2
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")


def test_database_connection_is_closed_if_setup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_connect = sqlite3.connect
    connections: list[sqlite3.Connection] = []

    class BrokenSetup(sqlite3.Connection):
        def execute(self, *args: Any, **kwargs: Any) -> Any:
            raise sqlite3.OperationalError("fixture PRAGMA failure")

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection = original_connect(*args, **kwargs, factory=BrokenSetup)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    with pytest.raises(sqlite3.OperationalError, match="fixture PRAGMA"):
        Database(tmp_path / "broken.sqlite3").connect()
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connections[0].cursor()


def test_lifespan_closes_bridge_even_when_body_raises(tmp_path: Path) -> None:
    bridge = FakeBridge()
    app = create_app(Settings(
        database_path=tmp_path / "cleanup.sqlite3", bills_roots="", credit_notes_roots="",
        debit_notes_roots="",
    ), bridge, start_worker=False)
    with pytest.raises(RuntimeError, match="fixture body failure"), TestClient(app):
        raise RuntimeError("fixture body failure")
    assert bridge.closed
