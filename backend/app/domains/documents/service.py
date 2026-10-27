"""Application service for document listing and preview lookup."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path

from app.domains.documents.models import DocumentRecord
from app.domains.documents.scanner import DocumentScanner


class DocumentService:
    def __init__(self, scanner: DocumentScanner) -> None:
        self.scanner = scanner

    def list_documents(
        self,
        category: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        categories: Iterable[str] | None = None,
    ) -> list[DocumentRecord]:
        if category is not None and categories is not None:
            raise ValueError("Use category or categories, not both")
        selected_categories = tuple(categories) if categories is not None else None
        if category is not None:
            selected_categories = (category,)
        return self.scanner.scan(selected_categories, start_date=start_date, end_date=end_date)

    def get_preview(self, file_id: str) -> DocumentRecord | None:
        return self.scanner.find_by_id(file_id)

    def get_previews(self, file_ids: Sequence[str]) -> dict[str, DocumentRecord]:
        """Resolve several file ids with a single scan instead of one scan per id."""

        requested = set(file_ids)
        return {
            record.file_id: record
            for record in self.scanner.scan()
            if record.file_id in requested
        }

    def validate_for_send(self, category: str, path: str) -> Path:
        return self.scanner.validate_path(category, Path(path))

    def update_roots(self, roots_by_category: dict[str, tuple[Path, ...]]) -> None:
        self.scanner.set_roots(roots_by_category)
