from contextlib import closing
from datetime import date
from io import BytesIO
from pathlib import Path

import pytest
from app.config import Settings
from app.db import Database
from app.domains.busy_ledger.parser import BusyLedgerError, parse_voucher_date
from app.domains.busy_ledger.repository import BusyLedgerRepository
from app.domains.busy_ledger.service import BusyLedgerService
from app.main import create_app
from fastapi.testclient import TestClient
from openpyxl import Workbook

from tests.fakes import FakeBridge


def make_ledger_workbook(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["BUSY Accounting Software"])
    sheet.append(["Sales Register", "01-04-2026 to 31-03-2027"])
    sheet.append([])
    sheet.append(["Vch Date", "Vch No.", "Vch Type", "Party Name"])
    sheet.append(
        [date(2026, 10, 25), "HST/26-27/1012", "Sales", "GAURI SHANKAR SALES CORPORATION PVT LTD"]
    )
    sheet.append([None, None, None, "Item continuation line"])
    sheet.append(
        [date(2026, 10, 25), "HST/26-27/1012", "Sales", "GAURI SHANKAR SALES CORPORATION PVT LTD"]
    )
    sheet.append(
        [date(2026, 10, 26), "HST/26-27/1013", "Sales", "ABC TEXTILES"]
    )
    serial = (date(2026, 10, 27) - date(1899, 12, 30)).days
    sheet.append([serial, "HST/26-27/1014", "Sales", "XYZ TRADERS"])
    sheet.append(["27-Oct-2026", "HST/26-27/1015", "Sales", "PQR ENTERPRISES"])
    sheet.append(["Grand Total", None, None, 250000])
    workbook.save(path)


def make_service(tmp_path: Path) -> BusyLedgerService:
    database = Database(tmp_path / "busy.sqlite3")
    database.initialize()
    return BusyLedgerService(
        BusyLedgerRepository(database),
        tmp_path / "inbox",
        financial_year="26-27",
    )


def test_importer_detects_headers_deduplicates_and_deletes_the_workbook(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    service.inbox_dir.mkdir()
    workbook_path = service.inbox_dir / "sales.xlsx"
    make_ledger_workbook(workbook_path)

    summary = service.import_inbox()

    assert summary.rows_found == 4
    assert summary.rows_imported == 4
    assert summary.files[0].detected_headers == {
        "date": "Vch Date",
        "voucher_no": "Vch No.",
        "voucher_type": "Vch Type",
        "party": "Party Name",
    }
    assert summary.files[0].deleted is True
    assert not workbook_path.exists()
    assert [(row.serial, row.voucher_date) for row in summary.files[0].sample_rows] == [
        (1012, date(2026, 10, 25)),
        (1013, date(2026, 10, 26)),
        (1014, date(2026, 10, 27)),
        (1015, date(2026, 10, 27)),
    ]
    assert summary.files[0].sample_rows[0].category == "bills"

    status = service.status()
    assert status.total_vouchers == 4
    assert status.last_sync_filename == "sales.xlsx"
    assert [(item.category, item.total_vouchers) for item in status.categories] == [
        ("bills", 4)
    ]
    assert status.categories[0].min_date == date(2026, 10, 25)
    assert status.categories[0].max_date == date(2026, 10, 27)


def test_reimporting_an_overlapping_range_updates_the_existing_voucher(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.inbox_dir.mkdir()
    first = service.inbox_dir / "first.xlsx"
    make_ledger_workbook(first)
    service.import_inbox()

    second = service.inbox_dir / "second.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Sales Register"])
    sheet.append(["Vch Date", "Vch No.", "Vch Type", "Party Name"])
    sheet.append(
        [date(2026, 10, 28), "HST/26-27/1012", "Sales", "GAURI SHANKAR SALES CORPORATION PVT LTD"]
    )
    workbook.save(second)

    summary = service.import_inbox()

    assert summary.rows_imported == 1
    assert not second.exists()
    assert service.status().total_vouchers == 4
    updated = service.repository.search("bills", 1012)
    assert len(updated) == 1
    assert updated[0].voucher_date == date(2026, 10, 28)


def test_dry_run_parses_and_deletes_without_writing_the_index(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.inbox_dir.mkdir()
    workbook_path = service.inbox_dir / "dry.xlsx"
    make_ledger_workbook(workbook_path)

    summary = service.import_workbooks([workbook_path], dry_run=True)

    assert summary.dry_run is True
    assert summary.rows_found == 4
    assert summary.rows_imported == 0
    assert summary.files[0].deleted is True
    assert not workbook_path.exists()
    assert service.status().total_vouchers == 0


def test_a_malformed_workbook_is_deleted_before_the_error_is_reported(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.inbox_dir.mkdir()
    bad = service.inbox_dir / "broken.xlsx"
    bad.write_bytes(b"this is not an xlsx workbook")

    with pytest.raises(BusyLedgerError):
        service.import_workbooks([bad])

    assert not bad.exists()
    assert service.status().last_sync_at is None
    with closing(service.repository.database.connect()) as connection:
        batch = connection.execute(
            "SELECT filename, status FROM busy_sync_batches"
        ).fetchone()
    assert batch["filename"] == "broken.xlsx"
    assert str(batch["status"]).startswith("failed:")


def test_voucher_date_parser_supports_serials_and_common_string_formats() -> None:
    serial = (date(2026, 10, 27) - date(1899, 12, 30)).days

    assert parse_voucher_date(serial) == date(2026, 10, 27)
    assert parse_voucher_date("25-10-2026") == date(2026, 10, 25)
    assert parse_voucher_date("25/10/2026") == date(2026, 10, 25)
    assert parse_voucher_date("25.10.26") == date(2026, 10, 25)
    assert parse_voucher_date("25-Oct-2026") == date(2026, 10, 25)
    assert parse_voucher_date("5-Apr-26") == date(2026, 4, 5)
    assert parse_voucher_date("not a date") is None


def test_import_endpoint_accepts_an_upload_and_reports_status(tmp_path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Credit Note Register"])
    sheet.append(["Vch Date", "Vch No.", "Vch Type", "Party Name"])
    sheet.append([date(2026, 10, 25), "CN/26-27/001", "Credit Note", "RAMESHWAR LAL"])
    buffer = BytesIO()
    workbook.save(buffer)

    settings = Settings(
        bills_roots="",
        credit_notes_roots="",
        debit_notes_roots="",
        database_path=tmp_path / "api.sqlite3",
        busy_inbox_dir=tmp_path / "inbox",
    )
    app = create_app(settings, FakeBridge(), start_worker=False)
    with TestClient(app) as client:
        response = client.post(
            "/api/busy-ledger/import",
            files={
                "file": (
                    "credit-notes.xlsx",
                    buffer.getvalue(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        status = client.get("/api/busy-ledger/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["rows_found"] == 1
    assert payload["rows_imported"] == 1
    assert payload["files"][0]["deleted"] is True
    assert payload["files"][0]["category"] == "credit_notes"
    assert status.status_code == 200
    assert status.json()["total_vouchers"] == 1
    assert status.json()["categories"][1] == {
        "category": "credit_notes",
        "total_vouchers": 1,
        "min_date": "2026-10-25",
        "max_date": "2026-10-25",
    }


def test_import_endpoint_dry_runs_workbooks_already_in_the_app_inbox(
    tmp_path: Path,
) -> None:
    settings = Settings(
        bills_roots="",
        credit_notes_roots="",
        debit_notes_roots="",
        database_path=tmp_path / "dry-run.sqlite3",
        busy_inbox_dir=tmp_path / "inbox",
    )
    settings.busy_inbox_dir.mkdir()
    workbook_path = settings.busy_inbox_dir / "sales.xlsx"
    make_ledger_workbook(workbook_path)
    app = create_app(settings, FakeBridge(), start_worker=False)

    with TestClient(app) as client:
        response = client.post(
            "/api/busy-ledger/import",
            data={"dry_run": "true", "category": "bills"},
        )
        status = client.get("/api/busy-ledger/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is True
    assert payload["rows_found"] == 4
    assert payload["rows_imported"] == 0
    assert payload["files"][0]["filename"] == "sales.xlsx"
    assert payload["files"][0]["deleted"] is True
    assert payload["files"][0]["category"] == "bills"
    assert not workbook_path.exists()
    assert status.json()["total_vouchers"] == 0

