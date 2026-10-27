"""Read voucher dates printed on BUSY-generated PDFs and cache them.

The Windows last-modified timestamp is not a reliable accounting date: copying
or reprinting a PDF changes it. Every PDF produced by BUSY carries the voucher
date in its text layer, so the dashboard can use that date without asking the
operator to export an Excel register first.

Extraction results (including "no date found") are cached by file id plus the
file's size and modification time. A full first scan reads every PDF; later
scans only re-read new or changed files.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from threading import Lock

import pymupdf

from app.db import Database
from app.domains.documents.models import DocumentRecord

logger = logging.getLogger(__name__)

_DATE_TOKEN = r"(\d{1,2})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{2,4})"

_BILL_PATTERNS = (
    re.compile(rf"\bDated\s*[:\-]?\s*{_DATE_TOKEN}", re.IGNORECASE),
    re.compile(rf"\bInvoice\s+Date\s*[:\-]?\s*{_DATE_TOKEN}", re.IGNORECASE),
    re.compile(rf"\bBill\s+Date\s*[:\-]?\s*{_DATE_TOKEN}", re.IGNORECASE),
    re.compile(rf"\bVoucher\s+Date\s*[:\-]?\s*{_DATE_TOKEN}", re.IGNORECASE),
)
_CREDIT_PATTERNS = (
    re.compile(rf"\bCr\.?\s*Note\s+Date\s*[:\-]?\s*{_DATE_TOKEN}", re.IGNORECASE),
    re.compile(rf"\bCredit\s+Note\s+Date\s*[:\-]?\s*{_DATE_TOKEN}", re.IGNORECASE),
    re.compile(rf"\bNote\s+Date\s*[:\-]?\s*{_DATE_TOKEN}", re.IGNORECASE),
)
_DEBIT_PATTERNS = (
    re.compile(rf"\bDr\.?\s*Note\s+Date\s*[:\-]?\s*{_DATE_TOKEN}", re.IGNORECASE),
    re.compile(rf"\bDebit\s+Note\s+Date\s*[:\-]?\s*{_DATE_TOKEN}", re.IGNORECASE),
    re.compile(rf"\bNote\s+Date\s*[:\-]?\s*{_DATE_TOKEN}", re.IGNORECASE),
)
_GENERIC_PATTERNS = (
    re.compile(rf"\bDated\s*[:\-]?\s*{_DATE_TOKEN}", re.IGNORECASE),
    re.compile(rf"\bInvoice\s+Date\s*[:\-]?\s*{_DATE_TOKEN}", re.IGNORECASE),
    re.compile(rf"\bVoucher\s+Date\s*[:\-]?\s*{_DATE_TOKEN}", re.IGNORECASE),
)
_PATTERNS_BY_CATEGORY = {
    "bills": _BILL_PATTERNS,
    "credit_notes": _CREDIT_PATTERNS,
    "debit_notes": _DEBIT_PATTERNS,
}
_CACHE_QUERY_CHUNK = 500
PdfDateExtractor = Callable[[Path, str], date | None]


def _normalized_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _parse_date(match: re.Match[str]) -> date | None:
    day, month, year = (int(group) for group in match.groups())
    if year < 100:
        year += 2000
    if not 2000 <= year <= 2100:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def extract_pdf_date(path: Path, category: str) -> date | None:
    """Return the voucher date printed on the first page, or ``None``.

    This deliberately reads only the PDF text layer. It never opens BUSY
    databases, XML, e-invoice temp files or any other application data.
    """

    try:
        with pymupdf.open(path) as document:  # type: ignore[no-untyped-call]
            if document.page_count == 0:
                return None
            text = document[0].get_text()
            if not text.strip() and document.page_count > 1:
                text = document[1].get_text()
    except Exception as exc:  # noqa: BLE001 - a bad PDF must not stop a scan
        logger.debug("Could not read PDF %s: %s", path, exc)
        return None
    normalized = _normalized_text(text)
    if not normalized:
        return None
    for pattern in _PATTERNS_BY_CATEGORY.get(category, _GENERIC_PATTERNS):
        match = pattern.search(normalized)
        if match is not None:
            parsed = _parse_date(match)
            if parsed is not None:
                return parsed
    return None


@dataclass(frozen=True, slots=True)
class _CachedDate:
    mtime_ns: int
    size_bytes: int
    voucher_date: date | None


@dataclass(frozen=True, slots=True)
class _DateWrite:
    file_id: str
    file_path: str
    mtime_ns: int
    size_bytes: int
    voucher_date: date | None


class PdfDateIndex:
    """SQLite cache of extracted PDF dates keyed by scanner file id."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def load(self, file_ids: Sequence[str]) -> dict[str, _CachedDate]:
        cached: dict[str, _CachedDate] = {}
        if not file_ids:
            return cached
        with closing(self.database.connect()) as connection:
            for start in range(0, len(file_ids), _CACHE_QUERY_CHUNK):
                chunk = list(file_ids[start : start + _CACHE_QUERY_CHUNK])
                placeholders = ",".join("?" for _ in chunk)
                rows = connection.execute(
                    "SELECT file_id, mtime_ns, size_bytes, voucher_date "
                    f"FROM pdf_date_index WHERE file_id IN ({placeholders})",
                    chunk,
                ).fetchall()
                for row in rows:
                    raw_date = row["voucher_date"]
                    cached[str(row["file_id"])] = _CachedDate(
                        mtime_ns=int(row["mtime_ns"]),
                        size_bytes=int(row["size_bytes"]),
                        voucher_date=date.fromisoformat(str(raw_date)) if raw_date else None,
                    )
        return cached

    def store(self, entries: Sequence[_DateWrite]) -> None:
        if not entries:
            return
        checked_at = datetime.now().astimezone().isoformat(timespec="seconds")
        rows = [
            (
                entry.file_id,
                entry.file_path,
                entry.mtime_ns,
                entry.size_bytes,
                entry.voucher_date.isoformat() if entry.voucher_date else None,
                checked_at,
            )
            for entry in entries
        ]
        with closing(self.database.connect()) as connection, connection:
            connection.executemany(
                "INSERT INTO pdf_date_index "
                "(file_id, file_path, mtime_ns, size_bytes, voucher_date, checked_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(file_id) DO UPDATE SET "
                "file_path = excluded.file_path, mtime_ns = excluded.mtime_ns, "
                "size_bytes = excluded.size_bytes, voucher_date = excluded.voucher_date, "
                "checked_at = excluded.checked_at",
                rows,
            )


def _file_stamp(record: DocumentRecord) -> tuple[int, int]:
    try:
        stat = record.path.stat()
    except OSError:
        return (
            int(record.modified_at.timestamp() * 1_000_000_000),
            record.size_bytes,
        )
    return stat.st_mtime_ns, stat.st_size


class PdfDateResolver:
    """Apply printed PDF dates to records that lack a verified BUSY date."""

    def __init__(
        self,
        database: Database,
        *,
        extractor: PdfDateExtractor = extract_pdf_date,
    ) -> None:
        self.index = PdfDateIndex(database)
        self.extractor = extractor
        # Serialize cold scans so two simultaneous preview requests do not parse
        # and write the same uncached PDFs twice.
        self._lock = Lock()

    def apply_effective_dates(self, records: Sequence[DocumentRecord]) -> list[DocumentRecord]:
        with self._lock:
            return self._apply_effective_dates(records)

    def _apply_effective_dates(self, records: Sequence[DocumentRecord]) -> list[DocumentRecord]:
        if not records:
            return []
        # A matched BUSY ledger row remains authoritative. PDF dates fill the
        # unmatched/ambiguous gap automatically.
        targets = [record for record in records if record.date_source == "file_fallback"]
        if not targets:
            return list(records)

        stamps = {record.file_id: _file_stamp(record) for record in targets}
        cached = self.index.load([record.file_id for record in targets])
        resolved: dict[str, date] = {}
        writes: list[_DateWrite] = []
        for record in targets:
            mtime_ns, size_bytes = stamps[record.file_id]
            cached_date = cached.get(record.file_id)
            if (
                cached_date is not None
                and cached_date.mtime_ns == mtime_ns
                and cached_date.size_bytes == size_bytes
            ):
                if cached_date.voucher_date is not None:
                    resolved[record.file_id] = cached_date.voucher_date
                continue
            voucher_date = self.extractor(record.path, record.category)
            writes.append(
                _DateWrite(
                    file_id=record.file_id,
                    file_path=str(record.path),
                    mtime_ns=mtime_ns,
                    size_bytes=size_bytes,
                    voucher_date=voucher_date,
                )
            )
            if voucher_date is not None:
                resolved[record.file_id] = voucher_date
        if writes:
            self.index.store(writes)

        return [
            replace(
                record,
                effective_date=resolved[record.file_id],
                date_source="pdf",
                match_status="pdf_extracted",
                matched_voucher_no=None,
            )
            if record.file_id in resolved
            else record
            for record in records
        ]
