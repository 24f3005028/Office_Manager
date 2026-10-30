from datetime import date
from pathlib import Path

import pytest
from app.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient

from tests.fakes import FakeBridge


def make_settings(tmp_path: Path, bills: Path, credit_notes: Path, debit_notes: Path) -> Settings:
    return Settings(
        bills_roots=[bills],
        credit_notes_roots=[credit_notes],
        debit_notes_roots=[debit_notes],
        database_path=tmp_path / "settings.sqlite3",
    )


def test_empty_optional_pdf_date_env_values_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PDF_DATE_MIN_DATE", "")
    monkeypatch.setenv("PDF_DATE_MAX_DATE", "")

    settings = Settings()

    assert settings.pdf_date_min_date is None
    assert settings.pdf_date_max_date is None


def test_pdf_date_env_values_are_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PDF_DATE_MIN_DATE", "2026-04-01")
    monkeypatch.setenv("PDF_DATE_MAX_DATE", "2027-03-31")

    settings = Settings()

    assert settings.pdf_date_min_date == date(2026, 4, 1)
    assert settings.pdf_date_max_date == date(2027, 3, 31)


def test_document_roots_are_saved_and_refresh_the_scanner(tmp_path: Path) -> None:
    bills = tmp_path / "bills"
    credit_notes = tmp_path / "credit-notes"
    debit_notes = tmp_path / "debit-notes"
    extra_bills = tmp_path / "extra-bills"
    for folder in (bills, credit_notes, debit_notes, extra_bills):
        folder.mkdir()
    (extra_bills / "HST-2.pdf").write_bytes(b"pdf")

    settings = make_settings(tmp_path, bills, credit_notes, debit_notes)
    app = create_app(settings, FakeBridge(), start_worker=False)

    with TestClient(app) as client:
        initial = client.get("/api/settings")
        assert initial.status_code == 200
        assert initial.json()["configured"] is True

        updated = client.put(
            "/api/settings/document-roots",
            json={
                "document_roots": {
                    "bills": [str(bills), str(extra_bills), str(extra_bills)],
                    "credit_notes": [str(credit_notes)],
                    "debit_notes": [str(debit_notes)],
                }
            },
        )
        assert updated.status_code == 200
        assert updated.json()["document_roots"]["bills"] == [str(bills), str(extra_bills)]

        documents = client.get("/api/documents", params={"document_types": "bill"})
        assert documents.status_code == 200
        assert [item["file_name"] for item in documents.json()] == ["HST-2.pdf"]

    second_app = create_app(settings, FakeBridge(), start_worker=False)
    with TestClient(second_app) as client:
        persisted = client.get("/api/settings")
        assert persisted.json()["document_roots"]["bills"] == [str(bills), str(extra_bills)]


def test_document_root_update_rejects_missing_folders(tmp_path: Path) -> None:
    bills = tmp_path / "bills"
    credit_notes = tmp_path / "credit-notes"
    debit_notes = tmp_path / "debit-notes"
    for folder in (bills, credit_notes, debit_notes):
        folder.mkdir()

    app = create_app(
        make_settings(tmp_path, bills, credit_notes, debit_notes), FakeBridge(), start_worker=False
    )
    with TestClient(app) as client:
        response = client.put(
            "/api/settings/document-roots",
            json={
                "document_roots": {
                    "bills": [str(tmp_path / "missing")],
                    "credit_notes": [str(credit_notes)],
                    "debit_notes": [str(debit_notes)],
                }
            },
        )
        assert response.status_code == 400
        assert "does not exist" in response.json()["detail"]
