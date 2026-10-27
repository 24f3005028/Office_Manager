"""Recursive, root-confined PDF scanner."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path

from app.domains.documents.models import (
    DocumentRecord,
    matches_modified_dates,
    natural_document_sort_key,
)

DOCUMENT_CATEGORIES = ("bills", "credit_notes", "debit_notes")


class DocumentScanner:
    def __init__(self, roots_by_category: Mapping[str, Sequence[Path]]) -> None:
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
                records_for_root = self._scan_root(
                    category, root_index, root, start_date=start_date, end_date=end_date
                )
                for record in records_for_root:
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
                if candidate.is_relative_to(resolved_root):
                    return candidate
        except OSError as exc:
            raise ValueError("Document is not accessible") from exc
        raise ValueError("Document is outside the configured document roots")

    def find_by_id(self, file_id: str) -> DocumentRecord | None:
        return next((record for record in self.scan() if record.file_id == file_id), None)

    def _scan_root(
        self,
        category: str,
        root_index: int,
        root: Path,
        *,
        start_date: date | None,
        end_date: date | None,
    ) -> list[DocumentRecord]:
        try:
            resolved_root = root.expanduser().resolve(strict=False)
            if not resolved_root.is_dir():
                return []
            candidates = resolved_root.rglob("*")
            records: list[DocumentRecord] = []
            for candidate in candidates:
                try:
                    if not candidate.is_file() or candidate.suffix.casefold() != ".pdf":
                        continue
                    resolved_candidate = candidate.resolve(strict=True)
                    if not resolved_candidate.is_relative_to(resolved_root):
                        continue
                    stat = resolved_candidate.stat()
                    modified_at = datetime.fromtimestamp(stat.st_mtime).astimezone()
                    if not matches_modified_dates(modified_at, start_date, end_date):
                        continue
                    relative_path = resolved_candidate.relative_to(resolved_root).as_posix()
                    records.append(
                        DocumentRecord(
                            file_id=self._file_id(category, resolved_candidate),
                            category=category,
                            file_name=resolved_candidate.name,
                            relative_path=relative_path,
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

    @staticmethod
    def _file_id(category: str, path: Path) -> str:
        stable_path = str(path).casefold()
        return hashlib.sha256(f"{category}:{stable_path}".encode()).hexdigest()[:32]
