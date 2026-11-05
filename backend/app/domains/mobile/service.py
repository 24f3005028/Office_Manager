"""On-demand report queue; file downloads and sends never start BUSY."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings
from app.domains.mobile.desktop import desktop_lock, office_warning
from app.domains.mobile.invoices import InvoiceCatalogue
from app.domains.mobile.reports import REPORT_START, OutstandingExporter, verify_report
from app.domains.mobile.store import MobileStore, now
from app.domains.pouncha_sync.parser import SyncError
from app.integrations.whatsapp.client import classify_send_error, parse_receipt


class MobileService:
    def __init__(
        self,
        settings: Settings,
        store: MobileStore,
        catalogue: InvoiceCatalogue,
        *,
        warning: Callable[[], bool] = office_warning,
        exporter: Any = None,
    ) -> None:
        self.settings, self.store, self.catalogue = settings, store, catalogue
        self.warning = warning
        self.exporter = exporter or OutstandingExporter(settings)
        self.directory = settings.database_path.expanduser().resolve().parent / "mobile-reports"
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mobile-reports")

    def close(self) -> None:
        self.pool.shutdown(wait=True, cancel_futures=True)

    def submit(self, user_id: str, party_id: str, as_of: date, key: str) -> dict[str, Any]:
        from zoneinfo import ZoneInfo

        if not REPORT_START <= as_of <= datetime.now(ZoneInfo("Asia/Kolkata")).date():
            raise ValueError("Choose a status date from 16 January 2025 through today.")
        party = self.store.party(party_id)
        if party is None:
            raise ValueError("Choose a party from the account list.")
        job, created = self.store.create_job(user_id, party, as_of.isoformat(), key)
        if created:
            self.pool.submit(self.execute, job["id"])
        return job

    def execute(self, job_id: str) -> None:
        job = self.store.job(job_id)
        if job is None or job["status"] != "queued":
            return
        try:
            with desktop_lock(self.settings.database_path):
                if not self.store.active(job["user_id"]):
                    raise SyncError("Mobile access was revoked.")
                self.store.update_job(job_id, status="warning")
                if not self.warning():
                    self.store.update_job(
                        job_id,
                        status="cancelled",
                        finished_at=now(),
                        error="Someone is using BUSY. Request cancelled by office.",
                    )
                    return
                if not self.store.active(job["user_id"]):
                    raise SyncError("Mobile access was revoked.")
                self.store.update_job(job_id, status="generating")
                directory = self.directory / job_id
                directory.mkdir(parents=True, exist_ok=True)
                as_of = date.fromisoformat(job["as_of"])
                path = self.exporter.export_report(job["party_name"], as_of, directory)
                if path.resolve().parent != directory.resolve():
                    raise SyncError("The report was not saved in its private output folder.")
                details = verify_report(path, job["party_name"], as_of)
                checksum = hashlib.sha256(path.read_bytes()).hexdigest()
                self.store.update_job(
                    job_id,
                    status="ready",
                    pdf_path=str(path),
                    pdf_hash=checksum,
                    details=json.dumps(details),
                    finished_at=now(),
                )
        except Exception as exc:
            self.store.update_job(
                job_id,
                status="failed",
                finished_at=now(),
                error=(
                    str(exc)
                    if isinstance(exc, (ValueError, SyncError))
                    else "The office could not finish safely. Ask the office to check BUSY."
                ),
            )

    def report_file(self, user_id: str, job_id: str) -> tuple[Path, dict[str, Any]]:
        job = self.store.job(job_id, user_id)
        if job is None or job["status"] != "ready":
            raise ValueError("This report is unavailable. Request a new statement.")
        if datetime.fromisoformat(job["finished_at"]) < datetime.now(UTC) - timedelta(hours=48):
            raise ValueError("This report has expired. Request a fresh statement.")
        path = Path(job["pdf_path"]).resolve(strict=True)
        if not path.is_relative_to(self.directory.resolve()) or not path.is_file():
            raise ValueError("Report file unavailable.")
        if hashlib.sha256(path.read_bytes()).hexdigest() != job["pdf_hash"]:
            raise ValueError("Report file changed. Request a new statement.")
        return path, job

    async def send(self, user: dict[str, Any], kind: str, file_id: str) -> dict[str, Any]:
        if kind == "report":
            path, _ = self.report_file(user["id"], file_id)
        else:
            path, _ = self.catalogue.file(file_id)
        content = path.read_bytes()
        checksum = hashlib.sha256(content).hexdigest()
        artifact = f"{kind}:{file_id}:{checksum}"
        delivery, created = self.store.delivery(user["id"], artifact)
        if not created:
            return self.public_delivery(delivery)
        try:
            if not self.store.active(user["id"]):
                raise ValueError("Mobile access was revoked.")
            headers = (
                {"x-api-key": self.settings.whatsapp_bridge_api_key}
                if self.settings.whatsapp_bridge_api_key
                else {}
            )
            async with httpx.AsyncClient(
                base_url=self.settings.whatsapp_bridge_url, timeout=60, headers=headers
            ) as client:
                response = await client.post(
                    "/send-document",
                    data={
                        "to": user["phone"] + "@c.us",
                        "operation_id": delivery["operation_id"],
                    },
                    files={"file": (path.name, content, "application/pdf")},
                )
                response.raise_for_status()
                receipt = parse_receipt(response.json(), delivery["operation_id"])
            delivery = self.store.finish_delivery(delivery["id"], "sent", receipt.message_id)
        except Exception as exc:
            error = classify_send_error(exc)
            delivery = self.store.finish_delivery(
                delivery["id"],
                "needs_review" if error.outcome == "unknown" else "not_sent",
                error=str(error),
            )
        return self.public_delivery(delivery)

    @staticmethod
    def public_delivery(row: dict[str, Any]) -> dict[str, Any]:
        return {key: row[key] for key in ("id", "status", "message_id", "error", "created_at")}
