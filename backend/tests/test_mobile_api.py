"""Gateway isolation, demand-only report generation and private artifact delivery."""

from __future__ import annotations

import shutil
import time
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import pymupdf
import pytest
from app.config import Settings
from app.db import Database
from app.domains.documents.scanner import DocumentScanner
from app.domains.mobile.accounts import account_names
from app.domains.mobile.invoices import InvoiceCatalogue
from app.domains.mobile.reports import verify_report
from app.domains.mobile.service import MobileService
from app.domains.mobile.store import MobileStore
from app.domains.pouncha_sync.parser import SyncError
from app.mobile_main import create_mobile_app
from fastapi.testclient import TestClient
from openpyxl import Workbook


def pdf(path: Path, text: str) -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((40, 40), text)
    document.save(path)
    document.close()


@pytest.fixture
def runtime(tmp_path: Path) -> tuple[MobileService, list[str]]:
    database = Database(tmp_path / "office.sqlite3")
    database.initialize()
    store = MobileStore(database)
    store.add_parties(["EXAMPLE PARTY"])
    bills = tmp_path / "bills"
    bills.mkdir()
    pdf(
        bills / "bill.pdf",
        "Invoice No.: HST/26-27/74\nDated : 05-11-2026\nBilled to : EXAMPLE PARTY",
    )
    reference = tmp_path / "reference.pdf"
    pdf(
        reference,
        "H.S. TRADERS\nBills Receivable\nAccount : EXAMPLE PARTY\n"
        "On Basis of : Due Date\nFrom 16-1-2025 to 5-11-2026\n"
        "Bills Status as on : 5-11-2026\n"
        "S.No. Dated Ref. No. Ref. Amt. Pending Amt. Due Days\n"
        "Grand Total 100.00 1.00\nOn Acc. : 0.00 ; Ledger Bal. : 1.00 Dr",
    )
    calls: list[str] = []

    class Exporter:
        def export_report(self, party: str, as_of: date, directory: Path) -> Path:
            calls.append("export")
            target = directory / "statement.pdf"
            shutil.copyfile(reference, target)
            return target

    def warning() -> bool:
        calls.append("warning")
        return True

    service = MobileService(
        Settings(database_path=database.path, _env_file=None),
        store,
        InvoiceCatalogue(DocumentScanner({"bills": [bills]})),
        warning=warning,
        exporter=Exporter(),
    )
    return service, calls


def login(client: TestClient, service: MobileService, name: str = "Employee") -> dict[str, str]:
    invite = service.store.invite(name, "919999999999")
    response = client.post("/mobile/v1/pair", json={"invite_code": invite["invite_code"]})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["token"]}


def test_gateway_has_no_office_routes_and_reads_never_start_busy(runtime: Any) -> None:
    service, calls = runtime
    with TestClient(create_mobile_app(service=service)) as client:
        assert client.get("/api/settings").status_code == 404
        assert client.get("/api/mobile-admin/status").status_code == 404
        assert client.get("/mobile/v1/parties").status_code == 401
        headers = login(client, service)
        assert len(client.get("/mobile/v1/parties", headers=headers).json()) == 1
        assert client.get("/mobile/v1/reports", headers=headers).json() == []
        assert (
            client.get("/mobile/v1/financial-years", headers=headers).json()["default"] == "26-27"
        )
        assert calls == []
        assert (
            client.get(
                "/mobile/v1/me", headers=headers | {"Origin": "https://evil.test"}
            ).status_code
            == 403
        )


def test_private_installer_does_not_need_a_session_before_pairing(
    runtime: Any, tmp_path: Path
) -> None:
    service, calls = runtime
    path = tmp_path / "app.apk"
    path.write_bytes(b"PK-test-apk")
    with TestClient(create_mobile_app(service=service, apk_path=path)) as client:
        response = client.get("/install/android.apk")
        assert response.status_code == 200
        assert response.content == b"PK-test-apk"
        assert "HS-Traders-Office.apk" in response.headers["content-disposition"]
        assert client.get("/mobile/v1/parties").status_code == 401
        assert calls == []


def test_report_warning_precedes_export_and_files_are_user_scoped(runtime: Any) -> None:
    service, calls = runtime
    with TestClient(create_mobile_app(service=service)) as client:
        alice, bob = login(client, service, "Alice"), login(client, service, "Bob")
        party = service.store.parties()[0]
        payload = {"party_id": party["id"], "as_of": "2026-11-05", "request_key": "test-request-1"}
        response = client.post("/mobile/v1/reports", json=payload, headers=alice)
        assert response.status_code == 202
        job_id = response.json()["id"]
        for _ in range(100):
            job = client.get(f"/mobile/v1/reports/{job_id}", headers=alice).json()
            if job["status"] in {"ready", "failed"}:
                break
            time.sleep(0.02)
        assert job["status"] == "ready", job
        assert job["details"]["pending_amount"] == "1.00"
        assert calls == ["warning", "export"]
        assert "pdf_path" not in job and "pdf_hash" not in job
        assert client.get(f"/mobile/v1/reports/{job_id}", headers=bob).status_code == 404
        assert client.get(f"/mobile/v1/reports/{job_id}/pdf", headers=bob).status_code == 404
        assert client.get(f"/mobile/v1/reports/{job_id}/pdf", headers=alice).content.startswith(
            b"%PDF"
        )
        assert client.post("/mobile/v1/reports", json=payload, headers=alice).json()["id"] == job_id
        assert calls == ["warning", "export"]


def test_office_cancel_never_exports(runtime: Any) -> None:
    service, calls = runtime
    service.warning = lambda: False
    party = service.store.parties()[0]
    invite = service.store.invite("Employee", "919999999999")
    job, _ = service.store.create_job(invite["id"], party, "2026-11-05", "test-cancel")
    service.execute(job["id"])
    assert service.store.job(job["id"])["status"] == "cancelled"
    assert calls == []
    service.close()


def test_invoice_exact_match_and_series_choice(runtime: Any) -> None:
    service, calls = runtime
    root = service.catalogue.scanner.roots_by_category["bills"][0]
    pdf(root / "other.pdf", "Invoice No.: HST/L/26-27/74\nBilled to : OTHER PARTY")
    pdf(root / "unrelated.pdf", "Invoice No.: HST/26-27/174\nBilled to : OTHER PARTY")
    results = service.catalogue.search("26-27", "74")
    assert len(results) == 2
    assert {row["bill_number"] for row in results} == {"HST/26-27/74", "HST/L/26-27/74"}
    assert len(service.catalogue.search("26-27", "HST/L/26-27/74")) == 1
    with pytest.raises(ValueError, match="different financial year"):
        service.catalogue.search("25-26", "HST/L/26-27/74")
    assert calls == []
    service.close()


def test_conflicting_invoice_copies_are_not_downloaded(runtime: Any) -> None:
    service, _ = runtime
    root = service.catalogue.scanner.roots_by_category["bills"][0]
    pdf(root / "different.pdf", "Invoice No.: HST/26-27/74\nBilled to : CONFLICTING PARTY")
    rows = service.catalogue.search("26-27", "74")
    assert all(row["conflicting_copies"] for row in rows)
    with pytest.raises(ValueError, match="Different PDFs"):
        service.catalogue.file(rows[0]["file_id"])
    service.close()


def test_report_verification_rejects_wrong_party(runtime: Any) -> None:
    service, _ = runtime
    path = service.settings.database_path.parent / "reference.pdf"
    with pytest.raises(SyncError, match="did not match"):
        verify_report(path, "WRONG PARTY", date(2026, 11, 5))
    with pytest.raises(SyncError, match="did not match"):
        verify_report(path, "EXAMPLE.PARTY", date(2026, 11, 5))
    service.close()


def test_definitely_not_sent_delivery_can_retry_but_unknown_cannot(runtime: Any) -> None:
    service, _ = runtime
    user = service.store.invite("Employee", "919999999999")
    first, created = service.store.delivery(user["id"], "invoice:example:hash")
    assert created
    service.store.finish_delivery(first["id"], "not_sent", error="Bridge offline")
    second, created = service.store.delivery(user["id"], "invoice:example:hash")
    assert created and first["operation_id"] != second["operation_id"]
    third, created = service.store.delivery(user["id"], "invoice:example:hash")
    assert not created and third["operation_id"] == second["operation_id"]
    service.close()


def test_account_import_keeps_trade_names_and_excludes_private_details() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["H.S. TRADERS"])
    sheet.append(["Name", "Alias", "Parent Group", "GSTIN", "Op. Bal.(Dr)"])
    sheet.append(["CUSTOMER", "ALIAS", "Sundry Debtors", "PRIVATE TAX ID", 100])
    sheet.append(["SUPPLIER", "", "Sundry Creditors", "PRIVATE TAX ID", 200])
    sheet.append(["EXPENSE", "", "Expenses (Indirect/Admn.)", "", 300])
    content = BytesIO()
    workbook.save(content)
    assert account_names(content.getvalue()) == ["CUSTOMER", "SUPPLIER"]


async def test_ambiguous_delivery_cannot_be_sent_again(runtime: Any, monkeypatch: Any) -> None:
    service, _ = runtime
    user = service.store.invite("Employee", "919999999999")
    person = next(row for row in service.store.users() if row["id"] == user["id"])
    file_id = service.catalogue.search("26-27", "74")[0]["file_id"]
    requests = []
    original_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise httpx.ReadTimeout("Unknown send result", request=request)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(**kwargs, transport=httpx.MockTransport(handler)),
    )
    first = await service.send(person, "invoice", file_id)
    second = await service.send(person, "invoice", file_id)
    assert first["status"] == second["status"] == "needs_review"
    assert len(requests) == 1
    assert b"919999999999@c.us" in requests[0].content
    service.close()
