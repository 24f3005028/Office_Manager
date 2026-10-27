from pathlib import Path

from app.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient

from tests.fakes import FakeBridge


def test_preview_returns_safe_metadata_and_rejects_unknown_id(tmp_path: Path) -> None:
    root = tmp_path / "bills"
    root.mkdir()
    pdf = root / "Invoice 7.pdf"
    pdf.write_bytes(b"private pdf bytes")
    settings = Settings(
        bills_roots=[root],
        credit_notes_roots=[],
        debit_notes_roots=[],
        database_path=tmp_path / "jobs.sqlite3",
    )
    app = create_app(settings, FakeBridge(), start_worker=False)

    with TestClient(app) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        documents = client.get("/api/documents")
        assert documents.status_code == 200
        metadata = documents.json()[0]
        preview = client.get(f"/api/documents/{metadata['file_id']}/preview")
        assert preview.status_code == 200
        assert "private pdf bytes" not in preview.text
        assert str(root) not in preview.text
        assert preview.json()["file_id"] == metadata["file_id"]
        assert client.get("/api/documents/does-not-exist/preview").status_code == 404


def test_preview_accepts_multiple_document_types(tmp_path: Path) -> None:
    bills = tmp_path / "bills"
    credit_notes = tmp_path / "credit-notes"
    bills.mkdir()
    credit_notes.mkdir()
    (bills / "HST-2 bill.pdf").write_bytes(b"bill")
    (credit_notes / "CN-1 note.pdf").write_bytes(b"credit")
    settings = Settings(
        bills_roots=[bills],
        credit_notes_roots=[credit_notes],
        debit_notes_roots=[],
        database_path=tmp_path / "jobs.sqlite3",
    )
    app = create_app(settings, FakeBridge(), start_worker=False)

    with TestClient(app) as client:
        response = client.get(
            "/api/documents",
            params={"document_types": "bill,credit_note"},
        )

    assert response.status_code == 200
    assert [item["category"] for item in response.json()] == ["bills", "credit_notes"]
