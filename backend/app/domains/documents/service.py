"""Application service for document listing, BUSY date resolution and preview."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from app.domains.documents.models import (
    DocumentRecord,
    matches_effective_dates,
    natural_document_sort_key,
)
from app.domains.documents.scanner import DocumentScanner

if TYPE_CHECKING:
    from app.domains.busy_ledger.service import BusyLedgerService
    from app.domains.documents.pdf_dates import PdfDateResolver


class DocumentService:
    def __init__(
        self,
        scanner: DocumentScanner,
        busy_ledger: BusyLedgerService | None = None,
        pdf_dates: PdfDateResolver | None = None,
    ) -> None:
        self.scanner = scanner
        self.busy_ledger = busy_ledger
        self.pdf_dates = pdf_dates

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

        # Scan first, then resolve accounting dates, then filter, then sort.
        # Filtering the filesystem date before resolution would drop a PDF whose
        # modified time changed after it was reprinted.
        records = self.scanner.scan(selected_categories)
        if self.busy_ledger is not None:
            records = self.busy_ledger.apply_effective_dates(records)
        if self.pdf_dates is not None:
            # A BUSY ledger match wins; otherwise use the voucher date printed
            # on the PDF itself. File timestamps are only the last resort.
            records = self.pdf_dates.apply_effective_dates(records)
        records = [
            record
            for record in records
            if matches_effective_dates(record, start_date, end_date)
        ]
        return sorted(records, key=natural_document_sort_key)

    def get_preview(self, file_id: str) -> DocumentRecord | None:
        return next(
            (record for record in self.list_documents() if record.file_id == file_id),
            None,
        )

    def get_previews(self, file_ids: Sequence[str]) -> dict[str, DocumentRecord]:
        """Resolve several file ids with a single scan instead of one scan per id."""

        requested = set(file_ids)
        return {
            record.file_id: record
            for record in self.list_documents()
            if record.file_id in requested
        }

    def validate_for_send(self, category: str, path: str) -> Path:
        return self.scanner.validate_path(category, Path(path))

    def update_roots(self, roots_by_category: dict[str, tuple[Path, ...]]) -> None:
        self.scanner.set_roots(roots_by_category)
