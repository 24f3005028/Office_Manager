import asyncio
import os
from datetime import datetime
from pathlib import Path

import pymupdf
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


def test_preview_and_job_share_date_first_order_with_category_and_root_ties(
    tmp_path: Path,
) -> None:
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
        expected = ["DN-1.pdf", "CN-2.pdf", "HST-10.pdf", "HST-2 A.pdf", "HST-2 Z.pdf", "CN-1.pdf"]
        assert [item["file_name"] for item in preview] == expected
        assert [item["effective_date"] for item in preview] == [
            "2026-10-18", "2026-10-19", "2026-10-20",
            "2026-10-21", "2026-10-22", "2026-10-23",
        ]
        assert all(item["date_source"] == "file_fallback" for item in preview)
        queued = client.post("/api/send-jobs", json={
            "file_ids": [item["file_id"] for item in reversed(preview)],
            "recipient": "fixture@c.us", "message": "",
        })
        assert queued.status_code == 201
        assert [item["file_name"] for item in queued.json()["files"]] == expected


def test_api_orders_multiple_dates_and_labels_bills_cn_dn_within_each_date(
    tmp_path: Path,
) -> None:
    bills = tmp_path / "bills"
    credit_notes = tmp_path / "credit-notes"
    bills.mkdir()
    credit_notes.mkdir()
    specs = [
        (bills, "HST-1.pdf", 25), (bills, "HST-2.pdf", 26),
        (bills, "HST-3.pdf", 27), (credit_notes, "CN-1.pdf", 25),
        (credit_notes, "CN-2.pdf", 27),
    ]
    for root, name, day in specs:
        path = root / name
        path.write_bytes(b"fixture pdf")
        stamp = datetime(2026, 10, day, 12, 0).timestamp()
        os.utime(path, (stamp, stamp))
    app = create_app(Settings(
        bills_roots=str(bills), credit_notes_roots=str(credit_notes),
        debit_notes_roots="", database_path=tmp_path / "multi-date.sqlite3",
    ), FakeBridge(), start_worker=False)
    with TestClient(app) as client:
        preview = client.get("/api/documents").json()
        assert [(item["file_name"], item["effective_date"]) for item in preview] == [
            ("HST-1.pdf", "2026-10-25"),
            ("CN-1.pdf", "2026-10-25"),
            ("HST-2.pdf", "2026-10-26"),
            ("HST-3.pdf", "2026-10-27"),
            ("CN-2.pdf", "2026-10-27"),
        ]
        queued = client.post("/api/send-jobs", json={
            "file_ids": [item["file_id"] for item in reversed(preview)],
            "recipient": "fixture@c.us",
        })
        assert queued.status_code == 201
        assert [
            (file["file_name"], file["date_label"]) for file in queued.json()["files"]
        ] == [
            ("HST-1.pdf", "25.10.26"),
            ("CN-1.pdf", "25.10.26"),
            ("HST-2.pdf", "26.10.26"),
            ("HST-3.pdf", "27.10.26"),
            ("CN-2.pdf", "27.10.26"),
        ]


def test_api_uses_the_voucher_date_printed_on_the_pdf_without_a_ledger(
    tmp_path: Path,
) -> None:
    root = tmp_path / "bills"
    root.mkdir()
    path = root / "HST-1 customer.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "TAX INVOICE")
    page.insert_text((72, 90), "Dated : 25-10-2026")
    document.save(path)
    document.close()
    stamp = datetime(2026, 10, 27, 12, 0).timestamp()
    os.utime(path, (stamp, stamp))
    app = create_app(
        Settings(
            bills_roots=str(root),
            credit_notes_roots="",
            debit_notes_roots="",
            database_path=tmp_path / "pdf-date.sqlite3",
        ),
        FakeBridge(),
        start_worker=False,
    )

    with TestClient(app) as client:
        preview = client.get("/api/documents").json()

    assert preview[0]["effective_date"] == "2026-10-25"
    assert preview[0]["date_source"] == "pdf"
    assert preview[0]["match_status"] == "pdf_extracted"


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
