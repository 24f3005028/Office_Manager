"""End-to-end BUSY desktop export and ledger import pipeline."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from app.domains.busy_automation.errors import BusyAutomationError
from app.domains.busy_automation.exporter import BusyExporter
from app.domains.busy_automation.lock import wait_for_user_idle
from app.domains.busy_automation.recipes import (
    BusyReportRecipe,
    recipe_for_category,
)
from app.domains.busy_automation.runner import (
    BusyAutomationConfig,
    BusyAutomationRequest,
    BusyExportRunner,
    IdleWaiter,
    SessionFactory,
)
from app.domains.busy_ledger.service import BusyImportSummary

logger = logging.getLogger(__name__)

__all__ = [
    "BusyAutomationConfig",
    "BusyAutomationPipeline",
    "BusyAutomationRequest",
    "BusyAutomationResult",
]

SUPPORTED_CATEGORIES = frozenset({"bills", "credit_notes", "debit_notes"})


class BusyLedgerImporter(Protocol):
    def import_workbooks(
        self,
        paths: Sequence[Path],
        *,
        category: str | None = None,
        dry_run: bool = False,
    ) -> BusyImportSummary: ...


@dataclass(frozen=True, slots=True)
class BusyAutomationResult:
    category: str
    start_date: date
    end_date: date
    filename: str
    rows_found: int
    rows_imported: int
    warnings: tuple[str, ...]
    duration_sec: float
    deleted: bool
    summary: BusyImportSummary


class BusyAutomationPipeline:
    """Run one guarded BUSY export and feed it to the existing ledger importer."""

    def __init__(
        self,
        config: BusyAutomationConfig,
        importer: BusyLedgerImporter,
        *,
        session_factory: SessionFactory | None = None,
        exporter: BusyExporter | None = None,
        recipe: BusyReportRecipe | None = None,
        idle_waiter: IdleWaiter = wait_for_user_idle,
        runner: BusyExportRunner | None = None,
    ) -> None:
        self.config = config
        self.importer = importer
        self._recipe = recipe
        self._runner = runner or BusyExportRunner(
            config,
            session_factory=session_factory,
            exporter=exporter,
            idle_waiter=idle_waiter,
        )

    def run(self, request: BusyAutomationRequest) -> BusyAutomationResult:
        if request.category not in SUPPORTED_CATEGORIES:
            raise BusyAutomationError(
                f"Unknown BUSY document category: {request.category}"
            )
        recipe = self._recipe or recipe_for_category(
            self.config.profile, request.category
        )
        summary, outcome = self._runner.run(
            request,
            recipe=recipe,
            consumer=lambda path: self.importer.import_workbooks(
                [path], category=request.category
            ),
            filename_prefix=f"busy_{request.category}",
        )
        return BusyAutomationResult(
            category=request.category,
            start_date=request.start_date,
            end_date=request.end_date,
            filename=outcome.exported_path.name,
            rows_found=summary.rows_found,
            rows_imported=summary.rows_imported,
            warnings=summary.warnings,
            duration_sec=outcome.duration_sec,
            deleted=outcome.deleted,
            summary=summary,
        )
