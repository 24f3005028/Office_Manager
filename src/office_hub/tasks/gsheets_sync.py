"""Google Sheets synchronization boundary."""

from __future__ import annotations

from typing import Any

from .base import TaskContext, TaskResult


class GoogleSheetsSync:
    name = "gsheets_sync"
    display_name = "Google Sheets sync"

    def execute(self, payload: dict[str, Any], context: TaskContext) -> TaskResult:
        sheet_id = payload.get("sheet_id") or context.settings.google_sheet_id
        if not sheet_id:
            raise ValueError("sheet_id is required or OFFICE_HUB_GOOGLE_SHEET_ID must be set")
        row_count = payload.get("row_count", 0)
        if not isinstance(row_count, int) or row_count < 0:
            raise ValueError("row_count must be a non-negative integer")

        plan = {
            "sheet_id": sheet_id,
            "worksheet": payload.get("worksheet", "Daily Import"),
            "row_count": row_count,
            "dispatch": "not performed",
        }
        context.info(f"Prepared Sheets sync for {row_count} row(s)")
        if context.dry_run or not context.settings.allow_external_actions:
            return TaskResult(summary=f"Sheets sync plan created for {row_count} row(s)", data=plan)

        raise RuntimeError(
            "Google Sheets client is not configured. Implement idempotent upsert behavior with "
            "service-account credentials before enabling external actions."
        )
