"""Shared guarded BUSY export runner.

Both the ledger import pipeline and the Pouncha daily sync drive the BUSY
desktop UI. Keeping the lock, idle guard, session reset and temp-file cleanup in
one place guarantees the same safety rules for every automation flow.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Protocol, TypeVar
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
)
from app.domains.busy_automation.session import (
    BusySession,
    BusySessionProtocol,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


class IdleWaiter(Protocol):
    def __call__(self, min_idle_seconds: float, *, timeout: float) -> None: ...


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
class BusyExportOutcome:
    requested_path: Path
    exported_path: Path
    duration_sec: float
    deleted: bool


class BusyExportRunner:
    """Run one guarded BUSY export and hand the workbook to a consumer."""

    def __init__(
        self,
        config: BusyAutomationConfig,
        *,
        session_factory: SessionFactory | None = None,
        exporter: BusyExporter | None = None,
        idle_waiter: IdleWaiter = wait_for_user_idle,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.config = config
        self._session_factory = session_factory or self._default_session_factory
        self._exporter = exporter or BusyExporter(config.profile)
        self._idle_waiter = idle_waiter
        self._now = now

    def run(
        self,
        request: BusyAutomationRequest,
        *,
        recipe: BusyReportRecipe,
        consumer: Callable[[Path], T],
        filename_prefix: str = "busy_export",
    ) -> tuple[T, BusyExportOutcome]:
        if request.start_date > request.end_date:
            raise ValueError("The report start date is after the end date.")
        if recipe.category != request.category:
            raise BusyAutomationError(
                f"The recipe for {recipe.category!r} cannot export "
                f"{request.category!r} documents."
            )

        started = time.monotonic()
        target = self._new_target(request, filename_prefix)
        with acquire_busy_lock(
            self.config.lock_path, self.config.timeout_seconds
        ):
            self._idle_waiter(
                self.config.idle_seconds,
                timeout=self.config.timeout_seconds,
            )
            session: BusySessionProtocol | None = None
            exported_path = target
            try:
                session = self._session_factory(self.config.profile)
                session.ensure_main_menu()
                recipe.open_report(
                    session,
                    ReportRequest(
                        start_date=request.start_date,
                        end_date=request.end_date,
                        series=request.series,
                    ),
                )
                exported_path = self._exporter.export(session, target)
                result = consumer(exported_path)
            finally:
                if session is not None:
                    try:
                        session.ensure_main_menu()
                    except Exception as exc:
                        logger.warning(
                            "Could not return BUSY to the main menu cleanly: %s",
                            exc,
                        )
                    try:
                        session.close()
                    except Exception as exc:
                        logger.warning(
                            "Could not release the BUSY session cleanly: %s", exc
                        )
                # The consumer owns deletion. This is a missing_ok safety net
                # for failures before consumption, or for a workbook Excel
                # still holds open. Excel is never killed.
                delete_file_with_retries(exported_path)
                if exported_path != target:
                    delete_file_with_retries(target)

        outcome = BusyExportOutcome(
            requested_path=target,
            exported_path=exported_path,
            duration_sec=time.monotonic() - started,
            deleted=not exported_path.exists(),
        )
        return result, outcome

    def _new_target(
        self, request: BusyAutomationRequest, filename_prefix: str
    ) -> Path:
        self.config.temp_dir.mkdir(parents=True, exist_ok=True)
        stamp = self._now().strftime("%Y%m%d-%H%M%S")
        unique = uuid4().hex[:8]
        safe_prefix = "".join(
            character if character.isalnum() or character in "_-" else "_"
            for character in filename_prefix
        )
        return self.config.temp_dir / (
            f"{safe_prefix}_"
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
