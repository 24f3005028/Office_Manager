from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from office_hub.app import create_app
from office_hub.config import Settings


@pytest.fixture
def app(tmp_path: Path):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "runtime",
        database_url=f"sqlite:///{(tmp_path / 'test.sqlite3').as_posix()}",
        billing_folder=tmp_path / "billing",
        enable_worker=False,
        enable_scheduler=False,
    )
    return create_app(settings)


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
