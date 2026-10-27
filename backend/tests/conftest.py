"""Every test uses temporary SQLite files, isolated settings, and mocked transports."""

import os
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest
from app.config import Settings


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    names = {name.casefold() for name in Settings.model_fields}
    names.update(
        str(field.validation_alias).casefold() for field in Settings.model_fields.values()
    )
    for name in tuple(os.environ):
        if name.casefold() in names:
            monkeypatch.delenv(name)

    connect = sqlite3.connect

    def isolated_connect(database: Any, *args: Any, **kwargs: Any) -> sqlite3.Connection:
        assert Path(database).resolve().is_relative_to(tmp_path.resolve()), (
            "Tests must only open databases inside their temporary fixture"
        )
        return connect(database, *args, **kwargs)

    async def no_async_network(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Real HTTP transport is forbidden in tests")

    def no_network(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Real HTTP transport is forbidden in tests")

    monkeypatch.setattr(sqlite3, "connect", isolated_connect)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", no_async_network)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", no_network)
