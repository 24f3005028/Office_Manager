"""On-demand report queue; file downloads and sends never start BUSY."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings
from app.domains.mobile.account_catalogue import AccountCatalogue
from app.domains.mobile.account_reports import (
    CopyAccountExporter,
    GroupBalancesExporter,
    financial_year,
    india_today,
    report_filename,
    verify_account_pdf,
)
from app.domains.mobile.all_outstanding import ALL_ID, ALL_NAME, AllAccountsExporter, verify_all_pdf
from app.domains.mobile.desktop import desktop_lock, office_warning
from app.domains.mobile.invoices import InvoiceCatalogue, invoice_filename
from app.domains.mobile.office import OfficeTools
from app.domains.mobile.reports import (
    REPORT_START,
    OutstandingExporter,
    verify_report,
)
from app.domains.mobile.store import MobileStore, now
from app.domains.mobile.tasks import TaskStore
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
        self.office = OfficeTools(store)
        self.tasks = TaskStore(store.database)
        self.accounts = AccountCatalogue(store)
        self.exporter = exporter or OutstandingExporter(settings)
        self.all_exporter = AllAccountsExporter(settings)
        self.directory = settings.database_path.expanduser().resolve().parent / "mobile-reports"
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mobile-reports")

    def close(self) -> None:
        self.pool.shutdown(wait=True, cancel_futures=True)

    def can_invite_users(self, user: dict[str, Any]) -> bool:
        return bool(
            self.settings.mobile_invite_admin_phone
            and user["phone"] == self.settings.mobile_invite_admin_phone
            and self.store.active(user["id"])
        )

    def _remove_report_directory(self, job_id: str) -> None:
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            return
        root = self.directory.resolve()
        directory = self.directory / job_id
        # Never follow a symlink or a stored, potentially stale PDF path.
        if directory.is_symlink() or directory.resolve().parent != root:
            return
        try:
            if directory.is_dir():
                shutil.rmtree(directory)
        except OSError:
            logging.getLogger(__name__).warning("Report cleanup deferred for %s", job_id)

    def cleanup_reports(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(hours=48)
        for job in self.store.cleanup_candidates():
            if job["status"] in {"failed", "cancelled"} or (
                job["status"] == "ready"
                and job["finished_at"]
                and datetime.fromisoformat(job["finished_at"]) < cutoff
            ):
                self._remove_report_directory(job["id"])

    def submit(self, user_id: str, party_id: str, as_of: date, key: str) -> dict[str, Any]:
        from zoneinfo import ZoneInfo

        if not REPORT_START <= as_of <= datetime.now(ZoneInfo("Asia/Kolkata")).date():
            raise ValueError("Choose a status date from 16 January 2025 through today.")
        self.cleanup_reports()
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
                if job["report_kind"] == "ledger":
                    start = date.fromisoformat(json.loads(job["parameters"])["start_date"])
                    path = CopyAccountExporter(self.settings, start).export_ledger(
                        job["party_name"], as_of, directory
                    )
                    details = verify_account_pdf(path, job["party_name"], as_of, start)
                elif job["report_kind"] == "group_balances":
                    path, snapshot = GroupBalancesExporter(self.settings).export_group(
                        job["party_name"], as_of, directory
                    )
                    content = json.dumps(snapshot, ensure_ascii=False).encode("utf-8")
                    (directory / "balances.json").write_bytes(content)
                    details = verify_account_pdf(path, job["party_name"], as_of)
                    details.update(
                        {key: value for key, value in snapshot.items() if key != "accounts"}
                    )
                    details["data_hash"] = hashlib.sha256(content).hexdigest()
                elif job["party_id"] == ALL_ID:
                    path, snapshot = self.all_exporter.export_all(as_of, directory)
                    content = json.dumps(snapshot, ensure_ascii=False).encode("utf-8")
                    (directory / "outstanding.json").write_bytes(content)
                    details = verify_all_pdf(path, snapshot, as_of)
                    details["data_hash"] = hashlib.sha256(content).hexdigest()
                else:
                    path = self.exporter.export_report(job["party_name"], as_of, directory)
                    details = verify_report(path, job["party_name"], as_of)
                if path.resolve().parent != directory.resolve():
                    raise SyncError("The report was not saved in its private output folder.")
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
            self._remove_report_directory(job_id)

    def submit_all(self, user_id: str, as_of: date, key: str) -> dict[str, Any]:
        from zoneinfo import ZoneInfo

        if not REPORT_START <= as_of <= datetime.now(ZoneInfo("Asia/Kolkata")).date():
            raise ValueError("Choose a status date from 16 January 2025 through today.")
        self.cleanup_reports()
        job, created = self.store.create_job(
            user_id, {"id": ALL_ID, "name": ALL_NAME}, as_of.isoformat(), key
        )
        if created:
            self.pool.submit(self.execute, job["id"])
        return job

    def submit_account(
        self,
        user_id: str,
        subject_id: str,
        kind: str,
        end: date,
        key: str,
        start: date | None = None,
    ) -> dict[str, Any]:
        today = india_today()
        if kind == "ledger":
            if start is None or not start <= end <= today:
                raise ValueError("Choose a valid start and end date, through today.")
            subject = self.accounts.account(subject_id)
            parameters = {"start_date": start.isoformat()}
        elif kind == "group_balances":
            fy, first, _ = financial_year(today)
            if not first <= end <= today:
                raise ValueError(
                    f"Choose a closing-balance date in financial year {fy}, through today."
                )
            subject = self.accounts.group(subject_id)
            parameters = {"financial_year": fy}
        else:
            raise ValueError("Unknown account report.")
        if subject is None:
            raise ValueError("Choose an account or group from the saved account list.")
        self.cleanup_reports()
        job, created = self.store.create_job(
            user_id, subject, end.isoformat(), key, report_kind=kind, parameters=parameters
        )
        if created:
            self.pool.submit(self.execute, job["id"])
        return job

    def balance_data(self, user_id: str, job_id: str) -> dict[str, Any]:
        pdf, job = self.report_file(user_id, job_id)
        if job["report_kind"] != "group_balances":
            raise ValueError("This is not a group closing-balance report.")
        path = pdf.parent / "balances.json"
        if path.is_symlink() or path.resolve().parent != pdf.parent:
            raise ValueError("Group balance data is unavailable.")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != json.loads(job["details"])["data_hash"]:
            raise ValueError("Group balance data changed. Request a fresh report.")
        result: dict[str, Any] = json.loads(content)
        return result

    def outstanding_data(self, user_id: str, job_id: str) -> dict[str, Any]:
        pdf, job = self.report_file(user_id, job_id)
        if job["party_id"] != ALL_ID:
            raise ValueError("This is not an all-account outstanding report.")
        path = pdf.parent / "outstanding.json"
        if path.is_symlink() or path.resolve().parent != pdf.parent:
            raise ValueError("Outstanding view is unavailable.")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != json.loads(job["details"])["data_hash"]:
            raise ValueError("Outstanding data changed. Request a fresh report.")
        result: dict[str, Any] = json.loads(content)
        return result

    def report_file(self, user_id: str, job_id: str) -> tuple[Path, dict[str, Any]]:
        self.cleanup_reports()
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
            path, report = self.report_file(user["id"], file_id)
            filename = report_filename(report)
        else:
            path, invoice = self.catalogue.file(file_id)
            filename = invoice_filename(invoice)
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
                    files={"file": (filename, content, "application/pdf")},
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
