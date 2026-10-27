import os
from datetime import date, datetime
from pathlib import Path

from app.domains.documents.scanner import DocumentScanner


def set_local_date(path: Path, value: date) -> None:
    timestamp = datetime.combine(value, datetime.min.time()).timestamp() + 3600
    os.utime(path, (timestamp, timestamp))


def test_scanner_recursively_finds_pdfs_and_applies_inclusive_local_dates(tmp_path: Path) -> None:
    root = tmp_path / "bills"
    nested = root / "2026" / "April"
    nested.mkdir(parents=True)
    first = nested / "Invoice 2.pdf"
    second = root / "Invoice 10.PDF"
    ignored = nested / "notes.txt"
    first.write_bytes(b"pdf")
    second.write_bytes(b"pdf")
    ignored.write_text("not a pdf", encoding="utf-8")
    set_local_date(first, date(2026, 4, 10))
    set_local_date(second, date(2026, 4, 11))

    scanner = DocumentScanner({"bills": (root,)})

    records = scanner.scan(("bills",), start_date=date(2026, 4, 10), end_date=date(2026, 4, 11))

    assert [record.file_name for record in records] == ["Invoice 2.pdf", "Invoice 10.PDF"]
    assert all(record.relative_path != "notes.txt" for record in records)
    assert records[0].path == first.resolve()


def test_scanner_rejects_send_paths_outside_configured_roots(tmp_path: Path) -> None:
    root = tmp_path / "bills"
    root.mkdir()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"pdf")
    scanner = DocumentScanner({"bills": (root,)})

    try:
        scanner.validate_path("bills", outside)
    except ValueError as exc:
        assert "outside" in str(exc).lower()
    else:
        raise AssertionError("An outside-root PDF was accepted")
