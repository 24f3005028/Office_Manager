"""Recursive, root-confined PDF scanner with system-directory exclusions."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path

from app.domains.documents.models import (
    DocumentRecord,
    matches_effective_dates,
    natural_document_sort_key,
)

DOCUMENT_CATEGORIES = ("bills", "credit_notes", "debit_notes")
DEFAULT_IGNORED_DIRECTORY_NAMES = frozenset(
    {"busywin", "einvoicetemp", "ewaybilltemp", "system", "xmppmessages"}
)


class DocumentScanner:
    def __init__(
        self,
        roots_by_category: Mapping[str, Sequence[Path]],
        *,
        ignored_directory_names: Iterable[str] | None = None,
    ) -> None:
        self.ignored_directory_names = frozenset(
            name.casefold()
            for name in (
                DEFAULT_IGNORED_DIRECTORY_NAMES
                if ignored_directory_names is None
                else ignored_directory_names
            )
            if name.strip()
        )
        self.set_roots(roots_by_category)

    def set_roots(self, roots_by_category: Mapping[str, Sequence[Path]]) -> None:
        self.roots_by_category = {
            category: tuple(Path(root) for root in roots)
            for category, roots in roots_by_category.items()
        }

    def scan(
        self,
        categories: Iterable[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[DocumentRecord]:
        if start_date is not None and end_date is not None and start_date > end_date:
            raise ValueError("start_date must be on or before end_date")

        selected = (
            tuple(categories)
            if categories is not None
            else tuple(
                category for category in DOCUMENT_CATEGORIES if category in self.roots_by_category
            )
        )
        records: dict[str, DocumentRecord] = {}
        for category in selected:
            if category not in self.roots_by_category:
                raise ValueError(f"Unknown document category: {category}")
            for root_index, root in enumerate(self.roots_by_category[category]):
                records_for_root = self._scan_root(category, root_index, root)
                for record in records_for_root:
                    if matches_effective_dates(record, start_date, end_date):
                        records.setdefault(record.file_id, record)
        return sorted(records.values(), key=natural_document_sort_key)

    def validate_path(self, category: str, path: Path) -> Path:
        """Resolve a PDF and ensure it remains inside one of the configured roots."""

        if category not in self.roots_by_category:
            raise ValueError(f"Unknown document category: {category}")
        try:
            candidate = path.expanduser().resolve(strict=True)
            if not candidate.is_file() or candidate.suffix.casefold() != ".pdf":
                raise ValueError("Only existing PDF files can be sent")
            for root in self.roots_by_category[category]:
                resolved_root = root.expanduser().resolve(strict=False)
                if not candidate.is_relative_to(resolved_root):
                    continue
                relative = candidate.relative_to(resolved_root)
                if self._has_ignored_directory(relative):
                    raise ValueError("Document is inside an excluded BUSY/system directory")
                return candidate
        except OSError as exc:
            raise ValueError("Document is not accessible") from exc
        raise ValueError("Document is outside the configured document roots")

    def find_by_id(self, file_id: str) -> DocumentRecord | None:
        return next((record for record in self.scan() if record.file_id == file_id), None)

    def _scan_root(self, category: str, root_index: int, root: Path) -> list[DocumentRecord]:
        try:
            resolved_root = root.expanduser().resolve(strict=False)
            if not resolved_root.is_dir():
                return []
            records: list[DocumentRecord] = []
            for current_dir, dirnames, filenames in os.walk(resolved_root, followlinks=False):
                dirnames[:] = sorted(
                    name
                    for name in dirnames
                    if name.casefold() not in self.ignored_directory_names
                )
                for filename in sorted(filenames):
                    if not filename.casefold().endswith(".pdf"):
                        continue
                    try:
                        candidate = Path(current_dir) / filename
                        resolved_candidate = candidate.resolve(strict=True)
                        if not resolved_candidate.is_relative_to(resolved_root):
                            continue
                        relative = resolved_candidate.relative_to(resolved_root)
                        if self._has_ignored_directory(relative):
                            continue
                        stat = resolved_candidate.stat()
                        modified_at = datetime.fromtimestamp(stat.st_mtime).astimezone()
                        records.append(
                            DocumentRecord(
                                file_id=self._file_id(category, resolved_candidate),
                                category=category,
                                file_name=resolved_candidate.name,
                                relative_path=relative.as_posix(),
                                size_bytes=stat.st_size,
                                modified_at=modified_at,
                                root_index=root_index,
                                path=resolved_candidate,
                            )
                        )
                    except (OSError, ValueError):
                        continue
            return records
        except OSError:
            return []

    def _has_ignored_directory(self, relative: Path) -> bool:
        return any(
            part.casefold() in self.ignored_directory_names
            for part in relative.parts[:-1]
        )

    @staticmethod
    def _file_id(category: str, path: Path) -> str:
        stable_path = str(path).casefold()
        return hashlib.sha256(f"{category}:{stable_path}".encode()).hexdigest()[:32]
