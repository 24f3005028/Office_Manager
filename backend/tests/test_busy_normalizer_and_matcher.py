import os
from datetime import date, datetime
from pathlib import Path

from app.db import Database
from app.domains.busy_ledger.matcher import apply_ledger_matches
from app.domains.busy_ledger.normalizer import parse_busy_voucher, parse_pdf_filename
from app.domains.busy_ledger.parser import ParsedLedgerRow
from app.domains.busy_ledger.repository import BusyLedgerRepository, LedgerEntry
from app.domains.busy_ledger.service import BusyLedgerService
from app.domains.documents.models import DocumentRecord
from app.domains.documents.scanner import DocumentScanner
from app.domains.documents.service import DocumentService


def document(
    root: Path,
    name: str,
    *,
    category: str = "bills",
    day: int = 27,
    root_index: int = 0,
) -> DocumentRecord:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4 fixture")
    return DocumentRecord(
        file_id=f"{category}-{root_index}-{name}",
        category=category,
        file_name=name,
        relative_path=name,
        size_bytes=1,
        modified_at=datetime(2026, 10, day, 12, 0).astimezone(),
        root_index=root_index,
        path=path.resolve(),
    )


def entry(
    entry_id: int,
    *,
    category: str = "bills",
    raw: str,
    series: str,
    serial: int,
    voucher_date: date,
    party: str,
    fy: str = "26-27",
) -> LedgerEntry:
    return LedgerEntry(
        id=entry_id,
        category=category,
        raw_voucher_no=raw,
        canonical_series=series,
        fy=fy,
        serial=serial,
        voucher_date=voucher_date,
        party_name=party,
        normalized_party=party.upper(),
    )


def test_busy_voucher_and_pdf_filename_normalize_to_the_same_serial() -> None:
    busy = parse_busy_voucher("HST/26-27/1012")
    filename = parse_pdf_filename("HST-1012 GAURI SHANKAR SALES CORP")

    assert busy is not None and filename is not None
    assert (busy.compact_series, busy.fy, busy.serial) == ("HST", "26-27", 1012)
    assert (filename.compact_series, filename.serial) == ("HST", 1012)
    assert filename.raw_party == "GAURI SHANKAR SALES CORP"


def test_busy_voucher_parses_financial_year_variants_and_leading_zeroes() -> None:
    variants = ["HST/26-27/001", "HST/2026-2027/1", "HST-26-27-0001"]

    parsed = [parse_busy_voucher(value) for value in variants]

    assert all(item is not None for item in parsed)
    assert {(item.fy, item.serial) for item in parsed if item is not None} == {
        ("26-27", 1)
    }


def test_series_alias_matches_hst_l_to_hsl(tmp_path: Path) -> None:
    ledger = entry(
        1,
        raw="HST-L/26-27/31",
        series="HSTL",
        serial=31,
        voucher_date=date(2026, 10, 25),
        party="GURU NANAK TEXTILE MILLS",
    )
    record = document(
        tmp_path,
        "HSL-31 GURU NANAK TEXTILE MILLS.pdf",
        day=27,
    )

    resolved = apply_ledger_matches(
        [record], {("bills", 31): [ledger]}, current_fy="26-27"
    )

    assert resolved[0].match_status == "matched"
    assert resolved[0].date_source == "busy"
    assert resolved[0].effective_date == date(2026, 10, 25)
    assert resolved[0].matched_voucher_no == "HST-L/26-27/31"


def test_series_disambiguates_a_shared_serial_across_hst_and_hsl(tmp_path: Path) -> None:
    hst = entry(
        1,
        raw="HST/26-27/31",
        series="HST",
        serial=31,
        voucher_date=date(2026, 10, 26),
        party="NAZIA TEXTILES",
    )
    hsl = entry(
        2,
        raw="HST-L/26-27/31",
        series="HSL",
        serial=31,
        voucher_date=date(2026, 10, 25),
        party="GURU NANAK TEXTILE MILLS",
    )
    hst_document = document(tmp_path / "hst", "HST-31 NAZIA TEXTILES.pdf", day=27)
    hsl_document = document(tmp_path / "hsl", "HSL-31 GURU NANAK TEXTILE MILLS.pdf", day=27)

    resolved = apply_ledger_matches(
        [hst_document, hsl_document],
        {("bills", 31): [hst, hsl]},
        current_fy="26-27",
    )

    assert [item.match_status for item in resolved] == ["matched", "matched"]
    assert [item.effective_date for item in resolved] == [
        date(2026, 10, 26),
        date(2026, 10, 25),
    ]
    assert [item.matched_voucher_no for item in resolved] == [
        "HST/26-27/31",
        "HST-L/26-27/31",
    ]


def test_party_tokens_disambiguate_duplicate_cn_one(tmp_path: Path) -> None:
    rameshwar = entry(
        1,
        category="credit_notes",
        raw="CN/26-27/001",
        series="CN",
        serial=1,
        voucher_date=date(2026, 10, 25),
        party="RAMESHWAR LAL SARUP CHAND",
    )
    manohar = entry(
        2,
        category="credit_notes",
        raw="CN/26-27/001",
        series="CN",
        serial=1,
        voucher_date=date(2026, 10, 26),
        party="MANOHAR LAL TEXTILE WORKS",
    )
    first = document(
        tmp_path / "cn-main",
        "CN-1 RAMESHWAR LAL SARUP CHAND.pdf",
        category="credit_notes",
        day=27,
    )
    second = document(
        tmp_path / "cn-ldh",
        "CN-1 MANOHAR LAL TEXTILE WORKS.pdf",
        category="credit_notes",
        day=27,
        root_index=1,
    )

    resolved = apply_ledger_matches(
        [first, second],
        {("credit_notes", 1): [rameshwar, manohar]},
        current_fy="26-27",
    )

    assert [item.match_status for item in resolved] == ["matched", "matched"]
    assert [item.effective_date for item in resolved] == [
        date(2026, 10, 25),
        date(2026, 10, 26),
    ]
    assert [item.matched_voucher_no for item in resolved] == [
        "CN/26-27/001",
        "CN/26-27/001",
    ]


def test_distinct_pdfs_cannot_claim_the_same_ledger_row(tmp_path: Path) -> None:
    shared = entry(
        1,
        category="credit_notes",
        raw="CN/26-27/001",
        series="CN",
        serial=1,
        voucher_date=date(2026, 10, 25),
        party="SAME PARTY TEXTILES",
    )
    first = document(
        tmp_path / "root-a",
        "CN-1 SAME PARTY TEXTILES.pdf",
        category="credit_notes",
        day=27,
    )
    second = document(
        tmp_path / "root-b",
        "CN-1 SAME PARTY TEXTILES.pdf",
        category="credit_notes",
        day=27,
        root_index=1,
    )

    resolved = apply_ledger_matches(
        [first, second], {("credit_notes", 1): [shared]}, current_fy="26-27"
    )

    assert [item.match_status for item in resolved] == ["ambiguous", "ambiguous"]
    assert [item.date_source for item in resolved] == [
        "file_fallback",
        "file_fallback",
    ]
    assert [item.effective_date for item in resolved] == [
        date(2026, 10, 27),
        date(2026, 10, 27),
    ]


def test_single_candidate_with_a_different_series_warns_but_uses_busy_date(
    tmp_path: Path,
) -> None:
    ledger = entry(
        1,
        raw="HST/26-27/99",
        series="HST",
        serial=99,
        voucher_date=date(2026, 10, 25),
        party="ANY PARTY",
    )
    record = document(tmp_path, "HSL-99 ANOTHER PARTY.pdf", day=27)

    resolved = apply_ledger_matches(
        [record], {("bills", 99): [ledger]}, current_fy="26-27"
    )

    assert resolved[0].match_status == "series_mismatch_warning"
    assert resolved[0].date_source == "busy"
    assert resolved[0].effective_date == date(2026, 10, 25)


def test_unparseable_filenames_fall_back_without_guessing(tmp_path: Path) -> None:
    ledger = entry(
        1,
        raw="HST/26-27/1",
        series="HST",
        serial=1,
        voucher_date=date(2026, 10, 25),
        party="PARTY",
    )
    records = [
        document(tmp_path, "File.pdf", day=27),
        document(tmp_path, "ajay.pdf", day=27),
    ]

    resolved = apply_ledger_matches(
        records, {("bills", 1): [ledger]}, current_fy="26-27"
    )

    assert [item.match_status for item in resolved] == ["unmatched", "unmatched"]
    assert [item.date_source for item in resolved] == [
        "file_fallback",
        "file_fallback",
    ]
    assert [item.effective_date for item in resolved] == [
        date(2026, 10, 27),
        date(2026, 10, 27),
    ]


def test_document_service_filters_on_busy_date_not_file_mtime(tmp_path: Path) -> None:
    database = Database(tmp_path / "busy.sqlite3")
    database.initialize()
    repository = BusyLedgerRepository(database)
    repository.store_import(
        filename="sales.xlsx",
        rows=[
            _parsed_row(
                raw="HST/26-27/1",
                series="HST",
                serial=1,
                voucher_date=date(2026, 10, 25),
                party="CUSTOMER",
            )
        ],
    )
    busy = BusyLedgerService(
        repository,
        tmp_path / "inbox",
        financial_year="26-27",
    )
    root = tmp_path / "bills"
    path = root / "HST-1 CUSTOMER.pdf"
    root.mkdir()
    path.write_bytes(b"%PDF-1.4 fixture")
    stamp = datetime(2026, 10, 27, 12, 0).timestamp()
    os.utime(path, (stamp, stamp))
    service = DocumentService(DocumentScanner({"bills": (root,)}), busy)

    on_busy_date = service.list_documents(
        start_date=date(2026, 10, 25), end_date=date(2026, 10, 25)
    )
    on_file_date = service.list_documents(
        start_date=date(2026, 10, 27), end_date=date(2026, 10, 27)
    )

    assert [item.file_name for item in on_busy_date] == ["HST-1 CUSTOMER.pdf"]
    assert on_busy_date[0].effective_date == date(2026, 10, 25)
    assert on_busy_date[0].date_source == "busy"
    assert on_file_date == []


def _parsed_row(
    *,
    raw: str,
    series: str,
    serial: int,
    voucher_date: date,
    party: str,
    category: str = "bills",
) -> ParsedLedgerRow:
    return ParsedLedgerRow(
        category=category,
        raw_voucher_no=raw,
        canonical_series=series,
        fy="26-27",
        serial=serial,
        voucher_date=voucher_date,
        party_name=party,
        normalized_party=party,
    )
