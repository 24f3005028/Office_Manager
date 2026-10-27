"""Document domain models and natural ordering helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

CATEGORY_ORDER = {"bills": 0, "credit_notes": 1, "debit_notes": 2}
DateSource = Literal["busy", "pdf", "file_fallback"]
MatchStatus = Literal[
    "matched", "unmatched", "ambiguous", "series_mismatch_warning", "pdf_extracted"
]
_NUMBER_RE = re.compile(r"\d+")


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    file_id: str
    category: str
    file_name: str
    relative_path: str
    size_bytes: int
    modified_at: datetime
    root_index: int
    path: Path
    # The effective accounting date comes from a matched BUSY ledger voucher,
    # or from the voucher date printed on the PDF. Until either resolver runs it
    # defaults to the local file date so scanner-only callers still get a
    # usable, deterministic date.
    effective_date: date | None = None
    date_source: DateSource = "file_fallback"
    match_status: MatchStatus = "unmatched"
    matched_voucher_no: str | None = None

    def __post_init__(self) -> None:
        if self.effective_date is None:
            object.__setattr__(
                self, "effective_date", self.modified_at.astimezone().date()
            )

    def safe_metadata(self) -> dict[str, Any]:
        """Return metadata suitable for API responses without exposing an absolute path."""

        return {
            "file_id": self.file_id,
            "category": self.category,
            "file_name": self.file_name,
            "relative_path": self.relative_path,
            "size_bytes": self.size_bytes,
            "modified_at": self.modified_at.isoformat(),
            "root_index": self.root_index,
            "effective_date": resolve_document_local_date(self).isoformat(),
            "date_source": self.date_source,
            "match_status": self.match_status,
            "matched_voucher_no": self.matched_voucher_no,
        }


def resolve_document_local_date(document: DocumentRecord) -> date:
    """Return the date that must drive filtering, preview and WhatsApp labels."""

    if document.effective_date is not None:
        return document.effective_date
    return document.modified_at.astimezone().date()


def matches_effective_dates(
    document: DocumentRecord, start_date: date | None, end_date: date | None
) -> bool:
    """Apply inclusive comparisons against the resolved accounting date."""

    local_date = resolve_document_local_date(document)
    if start_date is not None and local_date < start_date:
        return False
    if end_date is not None and local_date > end_date:
        return False
    return True


def _natural_text_key(value: str) -> tuple[tuple[int, object], ...]:
    parts = re.split(r"(\d+)", value.casefold())
    return tuple((1, int(part)) if part.isdigit() else (0, part) for part in parts if part)


def natural_filename_key(file_name: str) -> tuple[object, ...]:
    stem = Path(file_name).stem
    number_match = _NUMBER_RE.search(stem)
    if number_match:
        prefix = stem[: number_match.start()].strip().casefold()
        number: object = int(number_match.group())
        number_group = 0
    else:
        prefix = stem.casefold()
        number = 0
        number_group = 1
    return (prefix, number_group, number, stem.casefold())


def natural_document_sort_key(document: DocumentRecord) -> tuple[object, ...]:
    """Sort date-major, then category, configured folder, and natural filename.

    The order is the single source of truth for both preview and WhatsApp
    delivery: oldest effective date first, then bills, credit notes and debit
    notes, each folder 1 then folder 2, each bucket in natural filename order.
    """

    return (
        resolve_document_local_date(document),
        CATEGORY_ORDER.get(document.category, 99),
        document.root_index,
        natural_filename_key(document.file_name),
        _natural_text_key(document.relative_path),
    )
