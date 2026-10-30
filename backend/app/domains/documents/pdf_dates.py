"""Read voucher dates printed on BUSY-generated PDFs and cache them.

The Windows last-modified timestamp is not a reliable accounting date: copying
or reprinting a PDF changes it. Every PDF produced by BUSY carries the voucher
date in its text layer, so the dashboard can use that date without asking the
operator to export an Excel register first.

BUSY layouts can contain several dates on the first page (acknowledgement,
order, dispatch, reference-bill and e-way dates). The extractor therefore masks
known non-voucher contexts, prefers explicitly labelled voucher dates, and only
falls back to the top header block when no label is available.

Extraction results (including "no date found") are cached by file id plus the
file's size and modification time. A full first scan reads every PDF; later
scans only re-read new or changed files. The cache also stores an extractor
version so a smarter extractor re-evaluates old results instead of trusting
them forever.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from functools import partial
from pathlib import Path
from threading import Lock

import pymupdf

from app.db import Database
from app.domains.documents.models import DocumentRecord

logger = logging.getLogger(__name__)

# Bump this whenever the extraction rules change. Cached rows from older
# versions are ignored and re-extracted on the next scan.
PDF_DATE_EXTRACTOR_VERSION = 1

_HEADER_FRACTION = 0.4
_NEGATIVE_CONTEXT_WINDOW = 180
_LABEL_LOOKBACK = 200

_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

# Day-first only. BUSY prints Indian dates as DD-MM-YYYY, DD/MM/YYYY,
# DD.MM.YYYY or DD-MMM-YYYY; interpreting 05-10 as May 10 would be wrong.
_DATE_RE = re.compile(
    r"(?<!\d)(?P<day>\d{1,2})\s*[-./ ]\s*"
    r"(?P<month>\d{1,2}|[A-Za-z]{3,9})\s*[-./ ]\s*"
    r"(?P<year>\d{2,4})(?!\d)",
    re.IGNORECASE,
)

_STRONG_POSITIVE_RE = re.compile(
    r"\b(?:Invoice|Bill|Voucher|Credit\s*Note|Cr\.?\s*Note|"
    r"Debit\s*Note|Dr\.?\s*Note|C/N|D/N)\s*Date\b",
    re.IGNORECASE,
)
_WEAK_POSITIVE_RE = re.compile(r"\b(?:Dated|Date)\b", re.IGNORECASE)
_NEGATIVE_LABEL_RE = re.compile(
    r"\b(?:"
    r"Ack(?:nowledgement)?\.?\s*Date|"
    r"IRN|"
    r"Order\s*Date|"
    r"P\.?\s*O\.?\s*Date|"
    r"GR\s*Date|"
    r"RR\s*Date|"
    r"LR\s*Date|"
    r"Challan\s*Date|"
    r"E-?Way(?:\s*Bill)?(?:\s*Date)?|"
    r"Against\s*Bill|"
    r"Agst\.?\s*Bill|"
    r"Ref(?:erence)?\.?\s*Date|"
    r"Org(?:inal)?\.?\s*Inv(?:oice)?(?:\s*Date)?"
    r")\b",
    re.IGNORECASE,
)

PdfDateExtractor = Callable[[Path, str], date | None]


@dataclass(frozen=True, slots=True)
class _DateCandidate:
    value: date
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _PageText:
    text: str
    blocks: tuple[tuple[str, float], ...]
    height: float


def _normalized_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _default_date_bounds(today: date | None = None) -> tuple[date, date]:
    """Return a rolling Indian financial-year window plus a short future grace."""

    current = today or date.today()
    financial_year_start = current.year if current.month >= 4 else current.year - 1
    return date(financial_year_start - 1, 4, 1), current + timedelta(days=7)


def _resolve_bounds(
    min_date: date | None, max_date: date | None
) -> tuple[date, date]:
    default_min, default_max = _default_date_bounds()
    resolved_min = min_date or default_min
    resolved_max = max_date or default_max
    if resolved_min > resolved_max:
        raise ValueError("PDF date bounds are reversed")
    return resolved_min, resolved_max


def _parse_month(value: str) -> int | None:
    if value.isdigit():
        month = int(value)
        return month if 1 <= month <= 12 else None
    return _MONTHS.get(value[:3].casefold())


def _parse_date_match(match: re.Match[str]) -> date | None:
    day = int(match.group("day"))
    month = _parse_month(match.group("month"))
    year = int(match.group("year"))
    if year < 100:
        year += 2000
    if month is None or not 1 <= day <= 31:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _date_candidates(
    text: str, min_date: date, max_date: date
) -> list[_DateCandidate]:
    candidates: list[_DateCandidate] = []
    for match in _DATE_RE.finditer(text):
        value = _parse_date_match(match)
        if value is None or not min_date <= value <= max_date:
            continue
        candidates.append(_DateCandidate(value=value, start=match.start(), end=match.end()))
    return candidates


def _mask_negative_contexts(text: str) -> str:
    """Blank the first date after each known non-voucher date label.

    A plain character lookback is not enough for a line such as
    ``Against Bill No. HST-772 Dated : 14-09-2026`` because the voucher number
    sits between the label and the date. Masking the next date after the label
    handles that case while leaving a later ``Invoice Date`` intact.
    """

    masked = list(text)
    for label in _NEGATIVE_LABEL_RE.finditer(text):
        window_end = min(len(text), label.end() + _NEGATIVE_CONTEXT_WINDOW)
        date_match = _DATE_RE.search(text, label.end(), window_end)
        if date_match is None:
            continue
        between = text[label.end() : date_match.start()]
        if _STRONG_POSITIVE_RE.search(between):
            continue
        for index in range(date_match.start(), date_match.end()):
            masked[index] = " "
    return "".join(masked)


def _label_priority(text: str, index: int) -> int:
    """Return 0 for a strong voucher label, 1 for Dated/Date, 2 for none, 3 reject."""

    window = text[max(0, index - _LABEL_LOOKBACK) : index]
    strong = list(_STRONG_POSITIVE_RE.finditer(window))
    weak = list(_WEAK_POSITIVE_RE.finditer(window))
    negative = list(_NEGATIVE_LABEL_RE.finditer(window))
    last_strong = strong[-1].start() if strong else -1
    last_weak = weak[-1].start() if weak else -1
    last_negative = negative[-1].start() if negative else -1
    if last_negative > max(last_strong, last_weak):
        return 3
    if strong:
        return 0
    if weak:
        return 1
    return 2


def _unique_date(values: Sequence[date]) -> date | None:
    unique = set(values)
    return unique.pop() if len(unique) == 1 else None


def _read_page(path: Path) -> _PageText | None:
    try:
        with pymupdf.open(path) as document:  # type: ignore[no-untyped-call]
            if document.page_count == 0:
                return None
            for page_index in range(min(2, document.page_count)):
                page = document[page_index]
                text = _normalized_text(page.get_text())
                if not text:
                    continue
                blocks = tuple(
                    (_normalized_text(str(block[4])), float(block[1]))
                    for block in page.get_text("blocks")
                    if len(block) >= 5 and str(block[4]).strip()
                )
                return _PageText(text=text, blocks=blocks, height=float(page.rect.height))
    except Exception as exc:  # noqa: BLE001 - a bad PDF must not stop a scan
        logger.debug("Could not read PDF %s: %s", path, exc)
    return None


def _extract_from_page(page: _PageText, min_date: date, max_date: date) -> date | None:
    masked = _mask_negative_contexts(page.text)
    labelled = [
        candidate
        for candidate in _date_candidates(masked, min_date, max_date)
        if _label_priority(masked, candidate.start) == 0
    ]
    if labelled:
        return _unique_date([candidate.value for candidate in labelled])

    header_limit = page.height * _HEADER_FRACTION
    header_candidates: list[tuple[_DateCandidate, int]] = []
    for block_text, top in page.blocks:
        if top >= header_limit:
            continue
        masked_block = _mask_negative_contexts(block_text)
        for candidate in _date_candidates(masked_block, min_date, max_date):
            header_candidates.append(
                (candidate, _label_priority(masked_block, candidate.start))
            )

    weak = [
        candidate.value
        for candidate, priority in header_candidates
        if priority == 1
    ]
    if weak:
        return _unique_date(weak)

    unlabelled = [
        candidate.value
        for candidate, priority in header_candidates
        if priority == 2
    ]
    if unlabelled:
        return _unique_date(unlabelled)
    return None


def extract_pdf_date(
    path: Path,
    category: str,
    *,
    min_date: date | None = None,
    max_date: date | None = None,
) -> date | None:
    """Return the voucher date printed on the first page, or ``None``.

    ``category`` is kept in the signature for callers and future category
    tuning. The current rules use explicit labels rather than layout-specific
    category assumptions.

    This deliberately reads only the PDF text layer. It never opens BUSY
    databases, XML, e-invoice temp files or any other application data.
    """

    del category
    resolved_min, resolved_max = _resolve_bounds(min_date, max_date)
    page = _read_page(Path(path))
    if page is None:
        return None
    return _extract_from_page(page, resolved_min, resolved_max)


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
    extractor_version: int


class PdfDateIndex:
    """SQLite cache of extracted PDF dates keyed by scanner file id."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def load(
        self, file_ids: Sequence[str], extractor_version: int
    ) -> dict[str, _CachedDate]:
        cached: dict[str, _CachedDate] = {}
        if not file_ids:
            return cached
        with closing(self.database.connect()) as connection:
            for start in range(0, len(file_ids), _CACHE_QUERY_CHUNK):
                chunk = list(file_ids[start : start + _CACHE_QUERY_CHUNK])
                placeholders = ",".join("?" for _ in chunk)
                rows = connection.execute(
                    "SELECT file_id, mtime_ns, size_bytes, voucher_date "
                    f"FROM pdf_date_index WHERE file_id IN ({placeholders}) "
                    "AND extractor_version = ?",
                    [*chunk, extractor_version],
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
                entry.extractor_version,
                checked_at,
            )
            for entry in entries
        ]
        with closing(self.database.connect()) as connection, connection:
            connection.executemany(
                "INSERT INTO pdf_date_index "
                "(file_id, file_path, mtime_ns, size_bytes, voucher_date, "
                "extractor_version, checked_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(file_id) DO UPDATE SET "
                "file_path = excluded.file_path, mtime_ns = excluded.mtime_ns, "
                "size_bytes = excluded.size_bytes, voucher_date = excluded.voucher_date, "
                "extractor_version = excluded.extractor_version, "
                "checked_at = excluded.checked_at",
                rows,
            )


_CACHE_QUERY_CHUNK = 500


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
        extractor: PdfDateExtractor | None = None,
        extractor_version: int = PDF_DATE_EXTRACTOR_VERSION,
        min_date: date | None = None,
        max_date: date | None = None,
    ) -> None:
        self.index = PdfDateIndex(database)
        self.extractor_version = extractor_version
        self.min_date, self.max_date = _resolve_bounds(min_date, max_date)
        self.extractor: PdfDateExtractor = extractor or partial(
            extract_pdf_date, min_date=self.min_date, max_date=self.max_date
        )
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
        cached = self.index.load(
            [record.file_id for record in targets], self.extractor_version
        )
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
                    extractor_version=self.extractor_version,
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
