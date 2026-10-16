"""Safe BUSY report export and workbook-processing task.

The default mode is ``manual_import``: an operator exports a read-only report from BUSY into the
configured inbox and Office Hub parses only that copy. The optional ``ui`` mode is guarded by a
machine-specific pywinauto profile and never reads the Access database.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

from .base import TaskContext, TaskResult
from .busy_reports import (
    SUPPORTED_REPORTS,
    BusyReportError,
    parse_busy_workbook,
    write_normalized_workbook,
)
from .busy_ui import BusyUiExporter


def _parse_date(value: Any, field_name: str) -> date:
    if not isinstance(value, str) or not value:
        raise BusyReportError(f"{field_name} must be an ISO date such as 2026-10-14")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise BusyReportError(f"{field_name} must be an ISO date such as 2026-10-14") from exc


class BusyExporter:
    name = "busy_exporter"
    display_name = "BUSY report export"

    def execute(self, payload: dict[str, Any], context: TaskContext) -> TaskResult:
        report_type = payload.get("report_type")
        if report_type not in SUPPORTED_REPORTS:
            raise BusyReportError(
                f"report_type must be one of: {', '.join(sorted(SUPPORTED_REPORTS))}"
            )
        start = _parse_date(payload.get("start_date"), "start_date")
        end = _parse_date(payload.get("end_date") or payload.get("start_date"), "end_date")
        if end < start:
            raise BusyReportError("end_date cannot be before start_date")
        mode = payload.get("mode", "manual_import")
        if mode not in {"manual_import", "ui"}:
            raise BusyReportError("mode must be manual_import or ui")

        plan = {
            "report_type": report_type,
            "period": {"start": start.isoformat(), "end": end.isoformat()},
            "format": "xlsx",
            "mode": mode,
            "inbox": str(context.settings.busy_inbox_dir),
            "dispatch": "manual_export_required" if mode == "manual_import" else "not_performed",
        }
        input_file = payload.get("input_file")
        if mode == "manual_import" and not input_file:
            context.info(f"Prepared manual BUSY {report_type} import plan")
            return TaskResult(
                summary="BUSY report export required before parsing",
                data={**plan, "instructions": self._manual_instructions(report_type, start, end)},
            )

        if mode == "ui":
            if context.dry_run or not context.settings.allow_external_actions:
                context.info(
                    "BUSY UI automation skipped because this job is dry-run or external "
                    "actions are disabled"
                )
                return TaskResult(
                    summary="BUSY UI export plan created; no desktop control performed",
                    data=plan,
                )
            input_path = context.settings.busy_inbox_dir / f"busy-export-{uuid4().hex}.xlsx"
            input_file = str(
                BusyUiExporter(context).export(
                    report_type=report_type,
                    start_date=start.isoformat(),
                    end_date=end.isoformat(),
                    output_path=input_path,
                )
            )

        source = Path(str(input_file))
        parsed = parse_busy_workbook(source, report_type, context.settings.busy_inbox_dir)
        artifact = write_normalized_workbook(parsed, context.settings.busy_reports_dir)
        relative_artifact = artifact.relative_to(context.settings.resolved_output_dir)
        context.info(f"Parsed BUSY {report_type} workbook and created normalized artifact")
        return TaskResult(
            summary=f"BUSY {report_type} report parsed",
            data={
                **plan,
                "dispatch": "completed",
                "source_file": parsed.source_file.name,
                "artifact": str(relative_artifact),
                "row_count": len(parsed.rows),
                "totals": parsed.totals,
                "warnings": list(parsed.warnings),
                "review_required": parsed.review_required,
            },
        )

    @staticmethod
    def _manual_instructions(report_type: str, start: date, end: date) -> list[str]:
        display_name = "Profit & Loss" if report_type == "profit_loss" else "Balance Sheet"
        return [
            f"Open BUSY and run the read-only {display_name} report.",
            f"Set the date range from {start.isoformat()} to {end.isoformat()}.",
            "Export as .xlsx using the report headers Section, Account, Debit, Credit, Amount.",
            "Copy the workbook into the configured BUSY inbox, then submit the job with "
            "input_file.",
        ]
