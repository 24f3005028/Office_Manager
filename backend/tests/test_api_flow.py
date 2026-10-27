import asyncio
import os
from datetime import datetime
from pathlib import Path

from app.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient

from tests.fakes import FakeBridge


def test_dashboard_payload_creates_and_processes_job(tmp_path: Path) -> None:
    root = tmp_path / "bills"
    root.mkdir()
    (root / "HST-1 customer.pdf").write_bytes(b"pdf")
    settings = Settings(
        bills_roots=[root],
        credit_notes_roots=[],
        debit_notes_roots=[],
        database_path=tmp_path / "jobs.sqlite3",
    )
    app = create_app(settings, FakeBridge(), start_worker=False)

    with TestClient(app) as client:
        document = client.get(
            "/api/documents", params={"document_types": "bill"}
        ).json()[0]
        queued = client.post(
            "/api/send-jobs",
            json={
                "file_ids": [document["file_id"]],
                "recipient": "1234567890@c.us",
                "message": "Documents for today",
            },
        )
        assert queued.status_code == 201
        assert queued.json()["status"] == "queued"

        assert asyncio.run(app.state.send_job_service.process_once()) is True
        completed = client.get(f"/api/send-jobs/{queued.json()['job_id']}")

    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["files"][0]["status"] == "sent"


def test_preview_and_job_share_type_first_natural_order_with_root_ties(tmp_path: Path) -> None:
    roots = [tmp_path / name for name in ("first-bills", "second-bills", "credit", "debit")]
    for root in roots:
        root.mkdir()
    # Deliberately conflicting timestamps, root folder names, and request order.
    specs = [
        (0, "HST-10.pdf", 20, 10), (0, "HST-2 Z.pdf", 22, 23),
        (1, "HST-2 A.pdf", 21, 5), (2, "CN-2.pdf", 19, 10),
        (2, "CN-1.pdf", 23, 10), (3, "DN-1.pdf", 18, 10),
    ]
    for root_index, name, day, hour in specs:
        path = roots[root_index] / name
        path.write_bytes(b"fixture pdf")
        stamp = datetime(2026, 10, day, hour).timestamp()
        os.utime(path, (stamp, stamp))
    app = create_app(Settings(
        bills_roots="|".join(str(path) for path in roots[:2]), credit_notes_roots=str(roots[2]),
        debit_notes_roots=str(roots[3]), database_path=tmp_path / "ordering.sqlite3",
    ), FakeBridge(), start_worker=False)
    with TestClient(app) as client:
        preview = client.get("/api/documents").json()
        expected = ["HST-2 Z.pdf", "HST-2 A.pdf", "HST-10.pdf", "CN-1.pdf", "CN-2.pdf", "DN-1.pdf"]
        assert [item["file_name"] for item in preview] == expected
        queued = client.post("/api/send-jobs", json={
            "file_ids": [item["file_id"] for item in reversed(preview)],
            "recipient": "fixture@c.us", "message": "",
        })
        assert queued.status_code == 201
        assert [item["file_name"] for item in queued.json()["files"]] == expected


def test_get_jobs_restores_unknown_outcomes_after_backend_restart(tmp_path: Path) -> None:
    root = tmp_path / "bills"
    root.mkdir()
    (root / "Bill 1.pdf").write_bytes(b"fixture")
    settings = Settings(
        bills_roots=str(root), credit_notes_roots="", debit_notes_roots="",
        database_path=tmp_path / "restore.sqlite3",
    )
    app = create_app(settings, FakeBridge(), start_worker=False)
    with TestClient(app) as client:
        document = client.get("/api/documents").json()[0]
        queued = client.post("/api/send-jobs", json={
            "file_ids": [document["file_id"]], "recipient": "fixture@c.us",
        }).json()
        claimed = app.state.send_job_service.repository.claim_next_file()
        assert claimed is not None
    restarted = create_app(settings, FakeBridge(), start_worker=False)
    with TestClient(restarted) as client:
        response = client.get("/api/send-jobs")
        assert response.status_code == 200
        restored = response.json()[0]
        assert restored["job_id"] == queued["job_id"]
        assert restored["status"] == "needs_review"
        assert restored["files"][0]["status"] == "unknown"
        assert restored["files"][0]["outcome"] == "unknown"
        assert restored["files"][0]["operation_id"] == queued["files"][0]["operation_id"]
        assert restored["error"]
