import logging
import os
from datetime import date, datetime
from pathlib import Path

from office_hub.config import Settings
from office_hub.tasks.base import TaskContext
from office_hub.tasks.whatsapp_sender import WhatsAppPdfSender, scan_pdfs


def test_scan_pdfs_filters_by_local_modified_date(tmp_path: Path) -> None:
    matching = tmp_path / "invoice-001.pdf"
    other = tmp_path / "invoice-002.pdf"
    matching.write_bytes(b"pdf")
    other.write_bytes(b"pdf")
    target = date(2026, 10, 14)
    timestamp = datetime(2026, 10, 14, 12, 0).timestamp()
    os.utime(matching, (timestamp, timestamp))

    result = scan_pdfs(tmp_path, target)

    assert result == [matching]


def test_whatsapp_task_returns_dry_run_plan(tmp_path: Path) -> None:
    billing = tmp_path / "billing"
    billing.mkdir()
    invoice = billing / "invoice.pdf"
    invoice.write_bytes(b"pdf")
    settings = Settings(_env_file=None, data_dir=tmp_path / "runtime", billing_folder=billing)
    context = TaskContext(
        settings=settings,
        job_id="test-job",
        dry_run=True,
        logger=logging.getLogger(),
    )

    result = WhatsAppPdfSender().execute(
        {"target_date": date.today().isoformat()},
        context,
    )

    assert result.data["file_count"] == 1
    assert result.data["dispatch"] == "not performed"
