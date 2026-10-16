"""Safe WhatsApp PDF discovery boundary.

The scanner is useful immediately and is intentionally separated from dispatch. A live provider
must be selected and implemented before this task sends anything externally.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from .base import TaskContext, TaskResult


def _target_date(value: Any) -> date:
    if value is None:
        return date.today()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError("target_date must be an ISO date such as 2026-10-14")


def scan_pdfs(folder: Path, target_date: date) -> list[Path]:
    """Return PDFs whose local filesystem modification date matches ``target_date``."""

    if not folder.exists():
        raise FileNotFoundError(f"Billing folder does not exist: {folder}")
    if not folder.is_dir():
        raise NotADirectoryError(f"Billing folder is not a directory: {folder}")

    return sorted(
        (
            path
            for path in folder.rglob("*.pdf")
            if datetime.fromtimestamp(path.stat().st_mtime).date() == target_date
        ),
        key=lambda path: path.name.casefold(),
    )


class WhatsAppPdfSender:
    name = "whatsapp_pdf_sender"
    display_name = "WhatsApp PDF sender"

    def execute(self, payload: dict[str, Any], context: TaskContext) -> TaskResult:
        configured_folder = Path(payload.get("folder") or context.settings.billing_folder)
        folder = configured_folder.expanduser().resolve()
        allowed_root = context.settings.billing_folder.expanduser().resolve()
        if not folder.is_relative_to(allowed_root):
            raise ValueError("folder must be inside the configured billing folder")

        selected_date = _target_date(payload.get("target_date"))
        pdfs = scan_pdfs(folder, selected_date)
        context.info(f"Discovered {len(pdfs)} PDF file(s) for {selected_date.isoformat()}")
        plan = {
            "folder": str(folder),
            "target_date": selected_date.isoformat(),
            "files": [path.name for path in pdfs],
            "file_count": len(pdfs),
            "dispatch": "not performed",
        }

        if context.dry_run or not context.settings.allow_external_actions:
            return TaskResult(summary=f"Dry run found {len(pdfs)} PDF file(s)", data=plan)

        raise RuntimeError(
            "WhatsApp dispatch is not configured. Implement an approved provider and recipient "
            "mapping before enabling external actions."
        )
