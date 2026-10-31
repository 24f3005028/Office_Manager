"""Pouncha daily sales sync orchestration."""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from app.config import Settings
from app.domains.busy_automation.errors import BusyNotRunningError
from app.domains.busy_automation.lock import acquire_busy_lock
from app.domains.busy_automation.profile import BusyUiProfile
from app.domains.busy_automation.recipes import AccountLedgerSalesRecipe
from app.domains.busy_automation.runner import (
    BusyAutomationRequest,
    BusyExportRunner,
)
from app.domains.busy_automation.session import busy_window_visible
from app.domains.pouncha_sync.models import (
    ParsedPounchaWorkbook,
    PounchaRunStatus,
    PounchaSyncRun,
    PounchaTrigger,
)
from app.domains.pouncha_sync.parser import (
    parse_pouncha_sales_workbook,
    write_pouncha_archive,
)
from app.domains.pouncha_sync.repository import PounchaSyncRepository
from app.domains.pouncha_sync.sheets_client import (
    PounchaSheetClient,
    rows_for_records,
    select_new_records,
)

logger = logging.getLogger(__name__)


class PounchaSyncError(RuntimeError):
    """Base error for the Pouncha sync domain."""


class PounchaNotConfiguredError(PounchaSyncError):
    """Raised when Sheets or BUSY automation is not configured."""


class PounchaBusyExporter(Protocol):
    @property
    def calibrated(self) -> bool: ...

    def export_sales(
        self, start_date: date, end_date: date
    ) -> ParsedPounchaWorkbook: ...


@dataclass(frozen=True, slots=True)
class PounchaSyncServiceStatus:
    configured: bool
    upload_configured: bool
    sheets_configured: bool
    busy_configured: bool
    busy_calibrated: bool
    sync_enabled: bool
    last_run: PounchaSyncRun | None
    active_run: PounchaSyncRun | None
    recent_runs: tuple[PounchaSyncRun, ...]


class BusyPounchaExporter:
    """Run the calibrated Account Ledger Sales recipe and parse its export."""

    def __init__(
        self,
        runner: BusyExportRunner,
        profile: BusyUiProfile,
    ) -> None:
        self.runner = runner
        self.profile = profile

    @property
    def calibrated(self) -> bool:
        return self.profile.account_ledger_sales.calibrated

    def export_sales(
        self, start_date: date, end_date: date
    ) -> ParsedPounchaWorkbook:
        recipe = AccountLedgerSalesRecipe(self.profile.account_ledger_sales)
        request = BusyAutomationRequest(
            start_date=start_date,
            end_date=end_date,
            category="bills",
        )
        parsed, _ = self.runner.run(
            request,
            recipe=recipe,
            consumer=parse_pouncha_sales_workbook,
            filename_prefix="pouncha_sales",
        )
        return parsed


class PounchaSyncService:
    def __init__(
        self,
        *,
        settings: Settings,
        repository: PounchaSyncRepository,
        sheets_client: PounchaSheetClient,
        exporter: PounchaBusyExporter | None = None,
        busy_available: Callable[[], bool] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.sheets_client = sheets_client
        self.exporter = exporter
        self._busy_available = busy_available or (
            lambda: busy_window_visible(settings.busy_window_title_re)
        )
        self._now = now or (lambda: datetime.now(self.timezone))
        self.timezone: tzinfo
        try:
            self.timezone = ZoneInfo(settings.pouncha_timezone)
        except Exception:  # pragma: no cover - invalid env value
            logger.warning(
                "Unknown POUNCHA_TIMEZONE %r; using UTC.",
                settings.pouncha_timezone,
            )
            self.timezone = UTC
        self._tasks: set[asyncio.Task[object]] = set()
        self._thread_lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return (
            self.settings.pouncha_sync_enabled
            and self.exporter is not None
            and self.busy_calibrated
            and self.sheets_client.configured
        )

    @property
    def upload_configured(self) -> bool:
        """The Excel fallback only needs Sheets, not the BUSY desktop."""

        return self.settings.pouncha_sync_enabled and self.sheets_client.configured

    @property
    def sheets_configured(self) -> bool:
        return self.sheets_client.configured

    @property
    def busy_configured(self) -> bool:
        return self.exporter is not None

    @property
    def busy_calibrated(self) -> bool:
        return self.exporter is not None and self.exporter.calibrated

    def today(self) -> date:
        return self._now().astimezone(self.timezone).date()

    def default_window(self) -> tuple[date, date]:
        today = self.today()
        return today - timedelta(days=self.settings.pouncha_sync_lookback_days), today

    def busy_available(self) -> bool:
        return self._busy_available()

    def status(self) -> PounchaSyncServiceStatus:
        return PounchaSyncServiceStatus(
            configured=self.configured,
            upload_configured=self.upload_configured,
            sheets_configured=self.sheets_configured,
            busy_configured=self.busy_configured,
            busy_calibrated=self.busy_calibrated,
            sync_enabled=self.settings.pouncha_sync_enabled,
            last_run=self.repository.last_run(),
            active_run=self.repository.active_run(),
            recent_runs=tuple(self.repository.list_runs(limit=10)),
        )

    def queue_busy_run(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        trigger_type: PounchaTrigger | str = PounchaTrigger.MANUAL_BUSY,
    ) -> PounchaSyncRun:
        self._ensure_configured()
        start, end = self._window(start_date, end_date)
        run = self.repository.create_run(
            run_id=uuid.uuid4().hex,
            trigger_type=str(trigger_type),
            start_date=start,
            end_date=end,
        )
        try:
            self._spawn(
                self.run_busy(
                    run.run_id,
                    start_date=start,
                    end_date=end,
                    trigger_type=trigger_type,
                )
            )
        except Exception as exc:
            self._complete_failure(run.run_id, exc)
            raise
        return run

    async def run_busy(
        self,
        run_id: str,
        *,
        start_date: date,
        end_date: date,
        trigger_type: PounchaTrigger | str,
        skip_when_busy_closed: bool = False,
    ) -> PounchaSyncRun:
        return await asyncio.to_thread(
            self._execute_busy,
            run_id,
            start_date,
            end_date,
            trigger_type,
            skip_when_busy_closed,
        )

    async def run_new_busy(
        self,
        *,
        trigger_type: PounchaTrigger | str,
        start_date: date | None = None,
        end_date: date | None = None,
        skip_when_busy_closed: bool = False,
    ) -> PounchaSyncRun:
        """Create an audit row and await one BUSY export (used by the scheduler)."""

        self._ensure_configured()
        start, end = self._window(start_date, end_date)
        run = self.repository.create_run(
            run_id=uuid.uuid4().hex,
            trigger_type=str(trigger_type),
            start_date=start,
            end_date=end,
        )
        return await self.run_busy(
            run.run_id,
            start_date=start,
            end_date=end,
            trigger_type=trigger_type,
            skip_when_busy_closed=skip_when_busy_closed,
        )

    def _execute_busy(
        self,
        run_id: str,
        start_date: date,
        end_date: date,
        trigger_type: PounchaTrigger | str,
        skip_when_busy_closed: bool,
    ) -> PounchaSyncRun:
        try:
            exporter = self.exporter
            if exporter is None:
                raise PounchaNotConfiguredError(
                    "BUSY automation is not configured for Pouncha sync."
                )
            if not exporter.calibrated:
                raise PounchaNotConfiguredError(
                    "The BUSY Account Ledger Sales recipe is not calibrated."
                )
            with acquire_busy_lock(
                self.settings.pouncha_lock_path,
                self.settings.busy_automation_timeout_seconds,
            ):
                self.repository.mark_running(run_id)
                parsed = exporter.export_sales(start_date, end_date)
                return self._finish_success(run_id, parsed)
        except BusyNotRunningError as exc:
            if skip_when_busy_closed:
                logger.info(
                    "Pouncha catch-up skipped: BUSY 21 is not running."
                )
                return self._complete_failure(
                    run_id,
                    exc,
                    status=PounchaRunStatus.SKIPPED,
                    message="Waiting for BUSY 21.",
                )
            self._complete_failure(run_id, exc)
            raise
        except Exception as exc:
            self._complete_failure(run_id, exc)
            raise

    def run_upload(
        self,
        *,
        filename: str,
        contents: bytes,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> PounchaSyncRun:
        self._ensure_upload_configured()
        start, end = self._window(start_date, end_date)
        run = self.repository.create_run(
            run_id=uuid.uuid4().hex,
            trigger_type=PounchaTrigger.MANUAL_EXCEL.value,
            start_date=start,
            end_date=end,
        )
        safe_name = Path(filename).name or "AccountLedger_Sales.xlsx"
        temp_path = (
            self.settings.pouncha_upload_dir
            / f"{run.run_id}_{safe_name}"
        )
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_bytes(contents)
        try:
            try:
                with self._thread_lock, acquire_busy_lock(
                    self.settings.pouncha_lock_path,
                    self.settings.busy_automation_timeout_seconds,
                ):
                    self.repository.mark_running(run.run_id)
                    parsed = parse_pouncha_sales_workbook(temp_path)
                    return self._finish_success(run.run_id, parsed)
            except Exception as exc:
                self._complete_failure(run.run_id, exc)
                raise
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError as exc:  # pragma: no cover - Windows file lock
                logger.warning("Could not delete the Pouncha upload: %s", exc)

    def _finish_success(
        self,
        run_id: str,
        parsed: ParsedPounchaWorkbook,
    ) -> PounchaSyncRun:
        warnings = list(parsed.warnings)
        archive_warning = self._write_archive(parsed)
        if archive_warning:
            warnings.append(archive_warning)
        appended = 0
        already = 0
        if parsed.records:
            existing = self.sheets_client.existing_voucher_keys()
            fresh, already = select_new_records(parsed.records, existing)
            appended = self.sheets_client.append_rows(rows_for_records(fresh))
        self.repository.complete_run(
            run_id,
            status=PounchaRunStatus.SUCCESS.value,
            exported_sale_count=len(parsed.records),
            already_in_sheet_count=already,
            appended_count=appended,
            warnings=warnings,
        )
        completed = self.repository.get_run(run_id)
        if completed is None:  # pragma: no cover - defensive
            raise PounchaSyncError(f"Pouncha run {run_id} disappeared from the audit log.")
        return completed

    def _write_archive(self, parsed: ParsedPounchaWorkbook) -> str | None:
        target = self.settings.pouncha_local_excel_path
        if target is None or not parsed.records:
            return None
        try:
            write_pouncha_archive(parsed.records, target)
            return None
        except Exception as exc:
            logger.warning("Could not write the Pouncha local archive: %s", exc)
            return f"Local archive could not be written: {exc}"

    def _complete_failure(
        self,
        run_id: str,
        exc: BaseException,
        *,
        status: PounchaRunStatus = PounchaRunStatus.FAILED,
        message: str | None = None,
    ) -> PounchaSyncRun:
        text = message or self._error_text(exc)
        self.repository.complete_run(
            run_id,
            status=status.value,
            error_message=text,
        )
        completed = self.repository.get_run(run_id)
        if completed is None:  # pragma: no cover - defensive
            raise PounchaSyncError(
                f"Pouncha run {run_id} disappeared from the audit log."
            ) from exc
        return completed

    def _ensure_configured(self) -> None:
        self._ensure_upload_configured()
        if self.exporter is None:
            raise PounchaNotConfiguredError(
                "BUSY automation is not available for Pouncha sync."
            )
        if not self.exporter.calibrated:
            raise PounchaNotConfiguredError(
                "The BUSY Account Ledger Sales recipe is not calibrated. Open "
                "BUSY 21, run scripts/inspect_busy_ui.py --watch --controls, "
                "fill config/busy_ui_profile.json, and set "
                "account_ledger_sales.calibrated to true."
            )

    def _ensure_upload_configured(self) -> None:
        if not self.settings.pouncha_sync_enabled:
            raise PounchaNotConfiguredError(
                "Pouncha sync is disabled. Set POUNCHA_SYNC_ENABLED=true."
            )
        if not self.sheets_client.configured:
            raise PounchaNotConfiguredError(
                "Google Sheets is not configured. Set POUNCHA_SPREADSHEET_ID, "
                "GOOGLE_SERVICE_ACCOUNT_FILE, and share the sheet with the "
                "service-account email as Editor."
            )

    def _window(
        self, start_date: date | None, end_date: date | None
    ) -> tuple[date, date]:
        default_start, default_end = self.default_window()
        start = start_date or default_start
        end = end_date or default_end
        if start > end:
            raise ValueError("The Pouncha sync start date is after the end date.")
        return start, end

    def _spawn(
        self, coroutine: Coroutine[Any, Any, PounchaSyncRun]
    ) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError as exc:
            raise PounchaSyncError(
                "Pouncha sync must be queued from the running API event loop."
            ) from exc
        task = loop.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._consume_task)

    def _consume_task(self, task: asyncio.Task[PounchaSyncRun]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        # The audit row already records the failure; retrieve the exception so
        # asyncio does not log an unhandled task warning for a background run.
        task.exception()

    @staticmethod
    def _error_text(exc: BaseException) -> str:
        text = str(exc).strip() or exc.__class__.__name__
        return text[:1000]


def create_pouncha_sync_service(
    settings: Settings,
    repository: PounchaSyncRepository,
    *,
    sheets_client: PounchaSheetClient | None = None,
) -> PounchaSyncService:
    """Build the production service, including the BUSY export runner."""

    from app.domains.busy_automation.runner import BusyAutomationConfig
    from app.domains.pouncha_sync.sheets_client import GoogleSheetsClient

    resolved_sheets = sheets_client or GoogleSheetsClient(
        spreadsheet_id=settings.pouncha_spreadsheet_id,
        tab_name=settings.pouncha_sheet_tab_name,
        service_account_file=(
            str(settings.google_service_account_file)
            if settings.google_service_account_file.is_file()
            else None
        ),
    )
    exporter: BusyPounchaExporter | None = None
    if settings.pouncha_sync_enabled:
        config = BusyAutomationConfig.from_settings(settings)
        exporter = BusyPounchaExporter(
            BusyExportRunner(config), config.profile
        )
    return PounchaSyncService(
        settings=settings,
        repository=repository,
        sheets_client=resolved_sheets,
        exporter=exporter,
    )
