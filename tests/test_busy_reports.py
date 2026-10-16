import logging
from pathlib import Path

import pytest
from openpyxl import Workbook

from office_hub.config import Settings
from office_hub.tasks.base import TaskContext
from office_hub.tasks.busy_exporter import BusyExporter
from office_hub.tasks.busy_reports import BusyReportError, parse_busy_workbook


def _make_workbook(path: Path, rows: list[list[object]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Section", "Account", "Debit", "Credit", "Amount"])
    for row in rows:
        sheet.append(row)
    workbook.save(path)


def test_profit_loss_workbook_is_parsed_and_normalized(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    source = inbox / "pnl.xlsx"
    _make_workbook(
        source,
        [
            ["Revenue", "Sales", 0, 125000, 125000],
            ["Expenses", "Rent", 20000, 0, 20000],
        ],
    )

    report = parse_busy_workbook(source, "profit_loss", inbox)

    assert report.totals == {"revenue": 125000.0, "expenses": 20000.0, "net_profit": 105000.0}
    assert report.review_required is False


def test_unrecognized_workbook_fails_closed(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    source = inbox / "unknown.xlsx"
    workbook = Workbook()
    workbook.active.append(["Description", "Value"])
    workbook.save(source)

    with pytest.raises(BusyReportError, match="Section, Account"):
        parse_busy_workbook(source, "profit_loss", inbox)


def test_busy_exporter_manual_import_creates_safe_artifact(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "runtime",
        billing_folder=tmp_path / "billing",
        output_dir=tmp_path / "output",
    )
    settings.ensure_runtime_dirs()
    source = settings.busy_inbox_dir / "pnl.xlsx"
    _make_workbook(source, [["Revenue", "Sales", 0, 10, 10], ["Expenses", "Rent", 2, 0, 2]])
    context = TaskContext(settings, "job-id", True, logging.getLogger())
    result = BusyExporter().execute(
        {
            "report_type": "profit_loss",
            "start_date": "2026-10-01",
            "end_date": "2026-10-31",
            "mode": "manual_import",
            "input_file": str(source),
        },
        context,
    )

    assert result.data["dispatch"] == "completed"
    assert (
        result.data["artifact"].startswith("busy-reports\\")
        or result.data["artifact"].startswith("busy-reports/")
    )
    assert (settings.resolved_output_dir / result.data["artifact"]).is_file()
