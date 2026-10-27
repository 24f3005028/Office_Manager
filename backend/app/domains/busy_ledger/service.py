"""BUSY ledger import orchestration and effective-date resolution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from uuid import uuid4

from app.domains.busy_ledger.matcher import apply_ledger_matches
from app.domains.busy_ledger.normalizer import DEFAULT_SERIES_ALIASES
from app.domains.busy_ledger.parser import (
    SUPPORTED_WORKBOOK_SUFFIXES,
    BusyLedgerError,
    ParsedLedgerRow,
    ParsedWorkbook,
    parse_busy_workbook,
    workbook_paths,
)
from app.domains.busy_ledger.repository import BusyLedgerRepository, BusyLedgerStatus
from app.domains.documents.models import DocumentRecord


@dataclass(frozen=True, slots=True)
class ImportedWorkbookSummary:
    filename: str
    category: str | None
    detected_headers: dict[str, str]
    rows_found: int
    rows_imported: int
    sample_rows: tuple[ParsedLedgerRow, ...]
    warnings: tuple[str, ...]
    min_date: date | None
    max_date: date | None
    deleted: bool


@dataclass(frozen=True, slots=True)
class BusyImportSummary:
    dry_run: bool
    files: tuple[ImportedWorkbookSummary, ...]

    @property
    def rows_found(self) -> int:
        return sum(item.rows_found for item in self.files)

    @property
    def rows_imported(self) -> int:
        return sum(item.rows_imported for item in self.files)

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(
            f"{item.filename}: {warning}"
            for item in self.files
            for warning in item.warnings
        )


class BusyLedgerService:
    def __init__(
        self,
        repository: BusyLedgerRepository,
        inbox_dir: Path,
        *,
        aliases: Mapping[str, str] | None = None,
        financial_year: str = "26-27",
    ) -> None:
        self.repository = repository
        self.inbox_dir = Path(inbox_dir)
        self.aliases = dict(DEFAULT_SERIES_ALIASES)
        if aliases:
            self.aliases.update({key.upper(): value.upper() for key, value in aliases.items()})
        self.financial_year = financial_year.strip() or "26-27"

    @property
    def inbox_directory(self) -> Path:
        return self.inbox_dir

    def apply_effective_dates(
        self, records: Sequence[DocumentRecord]
    ) -> list[DocumentRecord]:
        if not records:
            return []
        candidates = self.repository.load_entries({record.category for record in records})
        return apply_ledger_matches(
            records,
            candidates,
            aliases=self.aliases,
            current_fy=self.financial_year,
        )

    def save_upload(self, filename: str, content: bytes) -> Path:
        safe_name = Path(filename or "busy-ledger.xlsx").name.strip()
        suffix = Path(safe_name).suffix.casefold()
        if suffix not in SUPPORTED_WORKBOOK_SUFFIXES:
            raise BusyLedgerError(
                "Upload a BUSY Excel export (.xlsx, .xlsm or .xls)."
            )
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        target = self.inbox_dir / safe_name
        if target.exists():
            target = self.inbox_dir / f"{target.stem}-{uuid4().hex[:8]}{target.suffix}"
        target.write_bytes(content)
        return target

    def import_inbox(
        self, *, category: str | None = None, dry_run: bool = False
    ) -> BusyImportSummary:
        paths = workbook_paths(self.inbox_dir)
        if not paths:
            self.inbox_dir.mkdir(parents=True, exist_ok=True)
            raise BusyLedgerError(
                f"No BUSY workbook was uploaded and the inbox is empty: {self.inbox_dir}"
            )
        return self.import_workbooks(paths, category=category, dry_run=dry_run)

    def import_workbooks(
        self,
        paths: Sequence[Path],
        *,
        category: str | None = None,
        dry_run: bool = False,
    ) -> BusyImportSummary:
        summaries: list[ImportedWorkbookSummary] = []
        for path in paths:
            try:
                parsed = parse_busy_workbook(
                    path,
                    category_hint=category,
                    aliases=self.aliases,
                )
            except BusyLedgerError as exc:
                self.repository.record_failed_import(filename=path.name, error=str(exc))
                raise BusyLedgerError(f"{path.name}: {exc}") from exc
            summaries.append(self._store(parsed, dry_run=dry_run))
        return BusyImportSummary(dry_run=dry_run, files=tuple(summaries))

    def status(self) -> BusyLedgerStatus:
        return self.repository.status()

    def _store(self, parsed: ParsedWorkbook, *, dry_run: bool) -> ImportedWorkbookSummary:
        rows_imported = 0
        if not dry_run:
            rows_imported = self.repository.store_import(
                filename=parsed.source_file.name,
                rows=parsed.rows,
            )
        resolved_category = parsed.category_hint
        if resolved_category is None and parsed.rows:
            categories = {row.category for row in parsed.rows}
            if len(categories) == 1:
                resolved_category = categories.pop()
        return ImportedWorkbookSummary(
            filename=parsed.source_file.name,
            category=resolved_category,
            detected_headers=dict(parsed.detected_headers),
            rows_found=parsed.rows_found,
            rows_imported=rows_imported,
            sample_rows=parsed.rows[:10],
            warnings=parsed.warnings,
            min_date=parsed.min_date,
            max_date=parsed.max_date,
            deleted=parsed.deleted,
        )
