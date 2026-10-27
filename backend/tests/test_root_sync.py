from collections.abc import Sequence
from pathlib import Path

import httpx
import pytest
from app.config import Settings
from app.integrations.whatsapp.readiness import BridgeReadiness
from app.main import create_app
from fastapi.testclient import TestClient

from tests.fakes import FakeBridge
from tests.test_send_jobs import make_service


async def test_failed_root_sync_blocks_claim_and_retries_when_bridge_recovers(
    tmp_path: Path,
) -> None:
    service, bridge = make_service(tmp_path)
    bridge.sync_error = httpx.ConnectError("fixture offline")
    job = service.create([item.file_id for item in service.documents.list_documents()],
                         "fixture@c.us", None)
    for _ in range(3):
        assert not await service.process_once()
    saved = service.get(job.job_id)
    assert saved is not None and saved.status == "queued"
    assert saved.started_at is None
    assert all(file.attempt_count == 0 and file.status == "queued" for file in saved.files)
    assert bridge.events == []
    assert service.readiness.details()["queue_wait_reason"] == "roots_not_synced"
    assert service.readiness.details()["bridge_sync_error"] is not None
    bridge.sync_error = None
    assert await service.process_once()
    assert len(bridge.roots) == 4
    assert service.readiness.synced
    assert service.readiness.details()["bridge_sync_error"] is None


async def test_generation_change_and_observed_outage_each_force_resync(tmp_path: Path) -> None:
    service, bridge = make_service(tmp_path)
    assert not await service.process_once()  # Sync also runs when there are no jobs.
    assert len(bridge.roots) == 1
    assert not await service.process_once()
    assert len(bridge.roots) == 1
    bridge.generation += 1
    assert not await service.process_once()
    assert len(bridge.roots) == 2
    bridge.status_error = httpx.ConnectError("fixture restarting")
    assert not await service.process_once()
    assert not service.readiness.synced
    bridge.status_error = None
    assert not await service.process_once()
    assert len(bridge.roots) == 3


async def test_generation_change_during_sync_is_not_acknowledged() -> None:
    class RestartDuringSync(FakeBridge):
        async def set_allowed_roots(self, roots: Sequence[str]) -> None:
            await super().set_allowed_roots(roots)
            self.generation += 1

    bridge = RestartDuringSync()
    readiness = BridgeReadiness(bridge, lambda: [])
    status = await readiness.refresh()
    assert not readiness.ready
    assert not status["roots_synced"]
    assert "changed during sync" in status["bridge_sync_error"]


def test_settings_and_status_expose_sync_failures_retry_and_empty_root_revocation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "bills"
    root.mkdir()
    bridge = FakeBridge()
    app = create_app(Settings(
        database_path=tmp_path / "roots.sqlite3", bills_roots=str(root),
        credit_notes_roots="", debit_notes_roots="",
    ), bridge, start_worker=False)
    with TestClient(app) as client:
        assert client.get("/api/whatsapp/status").json()["roots_synced"]
        bridge.sync_error = httpx.ConnectError("fixture down")
        response = client.put("/api/settings/document-roots", json={"document_roots": {}})
        assert response.status_code == 200
        assert not response.json()["bridge_roots_synced"]
        assert response.json()["document_roots"] == {
            "bills": [], "credit_notes": [], "debit_notes": [],
        }
        persisted = client.get("/api/settings").json()
        assert persisted["bridge_sync_error"] is not None
        assert not persisted["roots_synced"]
        bridge.sync_error = None
        status = client.get("/api/whatsapp/status").json()
        assert status["roots_synced"]
        assert status["bridge_sync_error"] is None
        assert status["queue_wait_reason"] is None
        assert bridge.roots[-1] == []
        assert client.get("/api/settings").json()["bridge_roots_synced"]


@pytest.mark.parametrize("operation", ["start", "reconnect"])
def test_lifecycle_returns_status_without_waiting_for_root_sync(
    tmp_path: Path, operation: str,
) -> None:
    bridge = FakeBridge()
    bridge.sync_error = RuntimeError("must not synchronize during lifecycle request")
    app = create_app(Settings(
        database_path=tmp_path / "lifecycle.sqlite3", bills_roots="", credit_notes_roots="",
        debit_notes_roots="",
    ), bridge, start_worker=False)
    with TestClient(app) as client:
        response = client.post(f"/api/whatsapp/{operation}")
        assert response.status_code == 200
        status = response.json()
        assert status["status"] == "starting"
        assert status["initializing"] is True
        assert status["connected"] is False
        assert status["qr_available"] is False
        assert status["requires_action"] is None
        assert status["message"] is None
        assert status["generation"] == 2
        assert status["qr_revision"] == 0
        assert not status["roots_synced"]
        assert bridge.roots == []
        bridge.sync_error = None
        bridge.state = "ready"
        assert client.get("/api/whatsapp/status").json()["roots_synced"]
        assert bridge.roots == [[]]
