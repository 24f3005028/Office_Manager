"""Document domain models and natural ordering helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

CATEGORY_ORDER = {"bills": 0, "credit_notes": 1, "debit_notes": 2}
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

    def safe_metadata(self) -> dict[str, Any]:
        """Return metadata suitable for API responses without exposing an absolute path."""

        return {
            "file_id": self.file_id,
            "category": self.category,
            "file_name": self.file_name,
            "relative_path": self.relative_path,
            "size_bytes": self.size_bytes,
            "modified_at": self.modified_at.isoformat(),
        }


def _natural_text_key(value: str) -> tuple[tuple[int, object], ...]:
    parts = re.split(r"(\d+)", value.casefold())
    return tuple((1, int(part)) if part.isdigit() else (0, part) for part in parts if part)


def natural_document_sort_key(document: DocumentRecord) -> tuple[object, ...]:
    """Sort category, filename prefix/number, then folders and filename naturally."""

    stem = Path(document.file_name).stem
    number_match = _NUMBER_RE.search(stem)
    if number_match:
        prefix = stem[: number_match.start()].strip().casefold()
        number: object = int(number_match.group())
        number_group = 0
    else:
        prefix = stem.casefold()
        number = 0
        number_group = 1
    return (
        CATEGORY_ORDER.get(document.category, 99),
        prefix,
        number_group,
        number,
        document.root_index,
        _natural_text_key(document.relative_path),
    )


def matches_modified_dates(
    modified_at: datetime, start_date: date | None, end_date: date | None
) -> bool:
    """Apply inclusive comparisons against the local calendar date of a file."""

    local_date = modified_at.astimezone().date()
    if start_date is not None and local_date < start_date:
        return False
    if end_date is not None and local_date > end_date:
        return False
    return True
