"""Only explicit user requests execute this pipeline; no scheduler or startup tasks."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from app.config import Settings
from app.domains.mobile.desktop import desktop_lock
from app.domains.pouncha_sync.parser import Sale, SyncError, bill_key, parse_sales
from app.domains.pouncha_sync.repository import RunRepository
from app.domains.pouncha_sync.sheets import GoogleSheet, Snapshot, compare, equivalent


class SheetAdapter(Protocol):
    def read(self) -> Snapshot: ...
    def append(self, records: list[Sale], before: Snapshot) -> str: ...


class ExportAdapter(Protocol):
    def export(self, start: date, end: date, directory: Path) -> Path: ...


class PounchaService:
    def __init__(
        self,
        settings: Settings,
        repository: RunRepository,
        sheet: SheetAdapter | None = None,
        exporter: ExportAdapter | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.sheet = sheet or GoogleSheet(settings)
        self.exporter = exporter

    def status(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "manual_only": True,
            "scheduler_enabled": False,
            "sheet_url": "https://docs.google.com/spreadsheets/d/"
            + self.settings.pouncha_spreadsheet_id,
            "tab": self.settings.pouncha_sheet_tab_name,
            "recent_runs": self.repository.recent(),
            "configured": self.settings.pouncha_credentials_path.is_file(),
            "last_bill": None,
            "last_date": None,
            "bill_count": None,
            "sheet_error": None,
        }
        try:
            data = self.sheet.read()
            result.update(
                last_bill=data.last_bill,
                last_date=data.last_date.isoformat() if data.last_date else None,
                bill_count=len(data.bills),
            )
        except Exception as exc:
            result["sheet_error"] = (
                str(exc) if isinstance(exc, SyncError) else "Cannot read the sheet."
            )
        return result

    @staticmethod
    def validate_dates(start: date | None, end: date) -> None:
        if end > datetime.now(ZoneInfo("Asia/Kolkata")).date():
            raise SyncError("The end date cannot be in the future.")
        if start and start > end:
            raise SyncError("Start date must be on or before end date.")

    def queue(self, start: date | None, end: date, preview: bool, source: str) -> dict[str, Any]:
        self.validate_dates(start, end)
        return self.repository.create(
            source, preview, start.isoformat() if start else None, end.isoformat()
        )

    def execute(self, run_id: str, upload: bytes | None = None) -> None:
        run = self.repository.get(run_id)
        if run is None or run["status"] != "queued":
            return
        self.repository.update(run_id, status="running")
        uncertain = False
        try:
            before = self.sheet.read()
            end = date.fromisoformat(run["end_date"])
            # Continue includes the last recorded day, never skips its remaining bills.
            start = date.fromisoformat(run["start_date"]) if run["start_date"] else before.last_date
            if start is None:
                raise SyncError(
                    "The sheet is empty. Select a custom start date for the first sync."
                )
            self.validate_dates(start, end)
            self.repository.update(
                run_id,
                start_date=start.isoformat(),
                stage="exporting" if upload is None else "parsing",
            )
            with TemporaryDirectory(prefix="pouncha-") as temporary:
                directory = Path(temporary)
                if upload is not None:
                    path = directory / "uploaded-sales.xlsx"
                    path.write_bytes(upload)
                else:
                    if self.exporter is None:
                        raise SyncError("BUSY export adapter is not available on this computer.")
                    with desktop_lock(self.settings.database_path):
                        path = self.exporter.export(start, end, directory)
                self.repository.update(run_id, stage="parsing")
                records = parse_sales(path, self.settings.pouncha_company, start, end)
            self.repository.update(run_id, stage="comparing", exported_count=len(records))
            before = self.sheet.read()
            new, conflicts, existing = compare(records, before)
            warnings = [f"Existing bill differs and was preserved: {bill}" for bill in conflicts]
            self.repository.update(
                run_id,
                existing_count=existing,
                new_count=len(new),
                conflicts=conflicts,
                warnings=warnings,
                preview=[record.cells() for record in new[:100]],
            )
            if not run["preview_only"] and new:
                intended = [record.cells() for record in new]
                self.repository.update(run_id, stage="appending", intended_rows=intended)
                uncertain = True
                updated_range = self.sheet.append(new, before)
                self.repository.update(run_id, stage="verifying", updated_range=updated_range)
                after = self.sheet.read()
                if after.rows[: len(before.rows)] != before.rows:
                    raise SyncError(
                        "Existing rows changed during sync; check the sheet before another run."
                    )
                if not all(
                    bill_key(record.bill) in after.bills
                    and equivalent(
                        after.bills[bill_key(record.bill)],
                        record.cells(),
                    )
                    for record in new
                ):
                    raise SyncError(
                        "Appended rows could not be verified. Check the sheet before retrying."
                    )
                self.repository.update(run_id, appended_count=len(new))
            self.repository.update(
                run_id,
                status="success",
                stage="complete",
                finished_at=datetime.now(UTC).isoformat(),
            )
        except Exception as exc:
            message = (
                str(exc)
                if isinstance(exc, SyncError)
                else "Sync failed unexpectedly; check the local setup and retry manually."
            )
            self.repository.update(
                run_id,
                status="needs_review" if uncertain else "failed",
                error=message,
                finished_at=datetime.now(UTC).isoformat(),
            )

    def reconcile(self, run_id: str) -> dict[str, Any]:
        run = self.repository.get(run_id)
        if run is None or run["status"] != "needs_review":
            raise SyncError("This run is not awaiting review.")
        after = self.sheet.read()
        intended = run["intended_rows"]
        if intended and all(
            bill_key(row[1]) in after.bills
            and equivalent(
                after.bills[bill_key(row[1])],
                row,
            )
            for row in intended
        ):
            self.repository.update(
                run_id,
                status="success",
                stage="complete",
                error=None,
                appended_count=len(intended),
                finished_at=datetime.now(UTC).isoformat(),
            )
        else:
            raise SyncError(
                "The intended rows are missing or different. "
                "Check the sheet, then explicitly release this run."
            )
        return self.repository.public(self.repository.get(run_id) or {})

    def release(self, run_id: str) -> None:
        run = self.repository.get(run_id)
        if not run or run["status"] != "needs_review":
            raise SyncError("This run is not awaiting review.")
        self.repository.update(
            run_id,
            status="reviewed",
            error="Released after manual sheet review. No rows were resent.",
        )
