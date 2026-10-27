import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pymupdf
import pytest
from app.db import Database
from app.domains.documents.models import DocumentRecord
from app.domains.documents.pdf_dates import PdfDateResolver, extract_pdf_date
from app.domains.documents.scanner import DocumentScanner
from app.domains.documents.service import DocumentService


def make_pdf(path: Path, lines: list[str]) -> None:
    document = pymupdf.open()
    page = document.new_page()
    y = 72.0
    for line in lines:
        page.insert_text((72, y), line, fontsize=11)
        y += 18
    document.save(path)
    document.close()


def record_for(path: Path, *, file_id: str = "bill-1") -> DocumentRecord:
    stat = path.stat()
    return DocumentRecord(
        file_id=file_id,
        category="bills",
        file_name=path.name,
        relative_path=path.name,
        size_bytes=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime).astimezone(),
        root_index=0,
        path=path,
    )


def test_extracts_bill_date_printed_as_dated(tmp_path: Path) -> None:
    pdf = tmp_path / "HST-1012 customer.pdf"
    make_pdf(
        pdf,
        [
            "TAX INVOICE",
            "Invoice No. : HST/26-27/1012",
            "Dated : 26-09-2026",
        ],
    )

    assert extract_pdf_date(pdf, "bills") == date(2026, 9, 26)


def test_extracts_credit_note_date_with_label_and_value_on_separate_lines(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "CN-1 customer.pdf"
    make_pdf(
        pdf,
        [
            "Credit Note",
            "Cr. Note No.",
            ": 1/2026-27",
            "Cr. Note Date",
            ": 27-04-2026",
            "Org. Inv. Date",
            ": 24-04-2026",
        ],
    )

    assert extract_pdf_date(pdf, "credit_notes") == date(2026, 4, 27)


def test_extracts_debit_note_date_and_supports_two_digit_years(tmp_path: Path) -> None:
    pdf = tmp_path / "DN-1 customer.pdf"
    make_pdf(
        pdf,
        [
            "Debit Note",
            "Dr. Note No. : HST/1/26-27",
            "Dr. Note Date : 18-04-26",
        ],
    )

    assert extract_pdf_date(pdf, "debit_notes") == date(2026, 4, 18)


def test_missing_or_invalid_date_returns_none(tmp_path: Path) -> None:
    no_date = tmp_path / "no-date.pdf"
    make_pdf(no_date, ["TAX INVOICE", "No accounting date here"])
    invalid = tmp_path / "invalid.pdf"
    make_pdf(invalid, ["TAX INVOICE", "Dated : 31-02-2026"])

    assert extract_pdf_date(no_date, "bills") is None
    assert extract_pdf_date(invalid, "bills") is None
    assert extract_pdf_date(tmp_path / "missing.pdf", "bills") is None


def test_resolver_uses_printed_date_and_caches_the_result(tmp_path: Path) -> None:
    pdf = tmp_path / "HST-1012 customer.pdf"
    make_pdf(pdf, ["TAX INVOICE", "Dated : 26-09-2026"])
    database = Database(tmp_path / "cache.sqlite3")
    database.initialize()
    calls = 0

    def counting_extractor(path: Path, category: str) -> date | None:
        nonlocal calls
        calls += 1
        return extract_pdf_date(path, category)

    resolver = PdfDateResolver(database, extractor=counting_extractor)
    record = record_for(pdf)

    first = resolver.apply_effective_dates([record])
    second = resolver.apply_effective_dates([record])

    assert calls == 1
    for resolved in (first[0], second[0]):
        assert resolved.effective_date == date(2026, 9, 26)
        assert resolved.date_source == "pdf"
        assert resolved.match_status == "pdf_extracted"

    later = pdf.stat().st_mtime + 60
    os.utime(pdf, (later, later))
    refreshed = record_for(pdf)
    resolver.apply_effective_dates([refreshed])
    assert calls == 2


def test_resolver_does_not_override_a_busy_ledger_date(tmp_path: Path) -> None:
    pdf = tmp_path / "HST-1012 customer.pdf"
    make_pdf(pdf, ["TAX INVOICE", "Dated : 26-09-2026"])
    database = Database(tmp_path / "cache.sqlite3")
    database.initialize()
    resolver = PdfDateResolver(
        database,
        extractor=lambda _path, _category: pytest.fail("BUSY date must not be re-read"),
    )
    record = DocumentRecord(
        file_id="bill-1",
        category="bills",
        file_name=pdf.name,
        relative_path=pdf.name,
        size_bytes=pdf.stat().st_size,
        modified_at=datetime.fromtimestamp(pdf.stat().st_mtime).astimezone(),
        root_index=0,
        path=pdf,
        effective_date=date(2026, 9, 25),
        date_source="busy",
        match_status="matched",
        matched_voucher_no="HST/26-27/1012",
    )

    resolved = resolver.apply_effective_dates([record])

    assert resolved[0].effective_date == date(2026, 9, 25)
    assert resolved[0].date_source == "busy"


def test_service_filters_and_sorts_by_the_date_printed_on_the_pdf(tmp_path: Path) -> None:
    root = tmp_path / "bills"
    root.mkdir()
    earlier = root / "HST-1 earlier.pdf"
    later = root / "HST-2 later.pdf"
    make_pdf(earlier, ["TAX INVOICE", "Dated : 25-10-2026"])
    make_pdf(later, ["TAX INVOICE", "Dated : 26-10-2026"])
    # File timestamps are deliberately reversed and unrelated to the PDF dates.
    old_stamp = datetime(2026, 10, 27, 12, 0).timestamp()
    os.utime(earlier, (old_stamp, old_stamp))
    new_stamp = (datetime(2026, 10, 27, 12, 0) + timedelta(hours=1)).timestamp()
    os.utime(later, (new_stamp, new_stamp))
    database = Database(tmp_path / "dates.sqlite3")
    database.initialize()
    service = DocumentService(
        DocumentScanner({"bills": (root,)}),
        pdf_dates=PdfDateResolver(database),
    )

    all_documents = service.list_documents()
    first_day = service.list_documents(
        start_date=date(2026, 10, 25), end_date=date(2026, 10, 25)
    )

    assert [item.file_name for item in all_documents] == [earlier.name, later.name]
    assert [item.effective_date for item in all_documents] == [
        date(2026, 10, 25),
        date(2026, 10, 26),
    ]
    assert [item.date_source for item in all_documents] == ["pdf", "pdf"]
    assert [item.file_name for item in first_day] == [earlier.name]
