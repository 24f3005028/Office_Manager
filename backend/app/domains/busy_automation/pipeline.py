"""End-to-end BUSY desktop export and ledger import pipeline."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from app.config import Settings
from app.domains.busy_automation.errors import BusyAutomationError
from app.domains.busy_automation.exporter import BusyExporter
from app.domains.busy_automation.files import delete_file_with_retries
from app.domains.busy_automation.lock import (
    acquire_busy_lock,
    wait_for_user_idle,
)
from app.domains.busy_automation.profile import BusyUiProfile, load_profile
from app.domains.busy_automation.recipes import (
    BusyReportRecipe,
    ReportRequest,
    SalesRegisterRecipe,
)
from app.domains.busy_automation.session import (
    BusySession,
    BusySessionProtocol,
)
from app.domains.busy_ledger.service import BusyImportSummary

logger = logging.getLogger(__name__)


class BusyLedgerImporter(Protocol):
    def import_workbooks(
        self,
        paths: Sequence[Path],
        *,
        category: str | None = None,
        dry_run: bool = False,
    ) -> BusyImportSummary: ...


class IdleWaiter(Protocol):
    def __call__(
        self, min_idle_seconds: float, *, timeout: float
    ) -> None: ...


SessionFactory = Callable[[BusyUiProfile], BusySessionProtocol]


@dataclass(frozen=True, slots=True)
class BusyAutomationConfig:
    executable_path: Path
    window_title_re: str
    expected_company: str
    timeout_seconds: float
    idle_seconds: float
    temp_dir: Path
    lock_path: Path
    profile: BusyUiProfile

    @classmethod
    def from_settings(cls, settings: Settings) -> BusyAutomationConfig:
        return cls(
            executable_path=settings.busy_executable_path,
            window_title_re=settings.busy_window_title_re,
            expected_company=settings.busy_expected_company_substring,
            timeout_seconds=settings.busy_automation_timeout_seconds,
            idle_seconds=settings.busy_min_user_idle_seconds,
            temp_dir=settings.busy_automation_temp_dir,
            lock_path=settings.busy_lock_path,
            profile=load_profile(settings.busy_ui_profile_path),
        )


@dataclass(frozen=True, slots=True)
class BusyAutomationRequest:
    start_date: date
    end_date: date
    category: str = "bills"
    series: str | None = None


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
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.config = config
        self.importer = importer
        self._session_factory = session_factory or self._default_session_factory
        self._exporter = exporter or BusyExporter(config.profile)
        self._recipe = recipe or SalesRegisterRecipe(
            config.profile.sales_register
        )
        self._idle_waiter = idle_waiter
        self._now = now

    def run(self, request: BusyAutomationRequest) -> BusyAutomationResult:
        if request.category != "bills":
            raise BusyAutomationError(
                "Phase 2 automation supports the Sales Register (bills) only."
            )
        if request.start_date > request.end_date:
            raise ValueError("The report start date is after the end date.")

        started = time.monotonic()
        with acquire_busy_lock(
            self.config.lock_path, self.config.timeout_seconds
        ):
            self._idle_waiter(
                self.config.idle_seconds,
                timeout=self.config.timeout_seconds,
            )
            target = self._new_target(request)
            session: BusySessionProtocol | None = None
            summary: BusyImportSummary | None = None
            try:
                session = self._session_factory(self.config.profile)
                session.ensure_main_menu()
                self._recipe.open_report(
                    session,
                    ReportRequest(
                        start_date=request.start_date,
                        end_date=request.end_date,
                        series=request.series,
                    ),
                )
                self._exporter.export(session, target)
                summary = self.importer.import_workbooks(
                    [target], category=request.category
                )
            finally:
                if session is not None:
                    try:
                        session.close()
                    except Exception as exc:
                        logger.warning(
                            "Could not release the BUSY session cleanly: %s", exc
                        )
                # The parser owns deletion. This is a missing_ok safety net
                # for failures before parsing, or for a workbook Excel still
                # holds open. Excel is never killed.
                delete_file_with_retries(target)

        assert summary is not None
        return BusyAutomationResult(
            category=request.category,
            start_date=request.start_date,
            end_date=request.end_date,
            filename=target.name,
            rows_found=summary.rows_found,
            rows_imported=summary.rows_imported,
            warnings=summary.warnings,
            duration_sec=time.monotonic() - started,
            deleted=not target.exists(),
            summary=summary,
        )

    def _new_target(self, request: BusyAutomationRequest) -> Path:
        self.config.temp_dir.mkdir(parents=True, exist_ok=True)
        stamp = self._now().strftime("%Y%m%d-%H%M%S")
        unique = uuid4().hex[:8]
        return self.config.temp_dir / (
            "busy_sales_register_"
            f"{request.start_date:%Y%m%d}_{request.end_date:%Y%m%d}_"
            f"{stamp}_{unique}.xlsx"
        )

    def _default_session_factory(
        self, profile: BusyUiProfile
    ) -> BusySessionProtocol:
        return BusySession.attach(
            executable_path=self.config.executable_path,
            title_re=self.config.window_title_re,
            expected_company=self.config.expected_company,
            profile=profile,
            timeout=self.config.timeout_seconds,
        )
