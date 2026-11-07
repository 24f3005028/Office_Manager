"""Account reports use the existing warning, ownership and artifact guarantees."""

from __future__ import annotations

import time
from contextlib import closing
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import Mock
from urllib.parse import unquote

import pymupdf
import pytest
from app.config import Settings
from app.db import Database
from app.domains.documents.scanner import DocumentScanner
from app.domains.mobile import account_reports, account_routes
from app.domains.mobile import service as service_module
from app.domains.mobile.account_reports import (
    CopyAccountExporter,
    GroupBalancesExporter,
    financial_year,
    parse_group_balances,
    verify_account_pdf,
)
from app.domains.mobile.accounts import account_rows
from app.domains.mobile.group_pdf import render_group_pdf
from app.domains.mobile.invoices import InvoiceCatalogue
from app.domains.mobile.service import MobileService
from app.domains.mobile.store import SCHEMA as MOBILE_SCHEMA
from app.domains.mobile.store import MobileStore
from app.domains.pouncha_sync.parser import SyncError
from app.mobile_main import create_mobile_app
from fastapi.testclient import TestClient
from openpyxl import Workbook

DAY = date(2026, 11, 7)


def make_pdf(path: Path, text: str) -> None:
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((40, 40), text)
        document.save(path)


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[MobileService, list[str]]:
    database = Database(tmp_path / "office.sqlite3")
    database.initialize()
    store = MobileStore(database)
    store.add_parties(["EXAMPLE PARTY"])
    folder = tmp_path / "bills"
    folder.mkdir()
    calls: list[str] = []

    class Ledger:
        def __init__(self, settings: Settings, start: date) -> None:
            self.start = start

        def export_ledger(self, party: str, end: date, directory: Path) -> Path:
            calls.append("ledger")
            path = directory / "account.pdf"
            make_pdf(
                path,
                f"H.S. TRADERS\nAccount Ledger\nAccount : {party}\n"
                f"From {self.start:%d-%m-%Y} to {end:%d-%m-%Y}\n"
                "Date Vch/Bill No Debit(Rs.) Credit(Rs.)",
            )
            return path

    class Groups:
        def __init__(self, settings: Settings) -> None:
            pass

        def export_group(
            self, group: str, as_of: date, directory: Path
        ) -> tuple[Path, dict[str, Any]]:
            calls.append("group")
            path = directory / "group.pdf"
            make_pdf(
                path,
                f"H.S. TRADERS\nTrial Balance\nGroup : {group}\nAs on {as_of:%d-%m-%Y}\n"
                "Account Name Debit(Rs.) Credit(Rs.)",
            )
            return path, {
                "group_name": group,
                "as_of": as_of.isoformat(),
                "account_count": 1,
                "debit_total": "0.00",
                "credit_total": "123.45",
                "accounts": [
                    {
                        "name": "LOAN PARTY",
                        "debit": "0.00",
                        "credit": "123.45",
                        "balance": "123.45",
                        "side": "Cr",
                    }
                ],
            }

    def warning() -> bool:
        calls.append("warning")
        return True

    monkeypatch.setattr(service_module, "CopyAccountExporter", Ledger)
    monkeypatch.setattr(service_module, "GroupBalancesExporter", Groups)
    monkeypatch.setattr(service_module, "india_today", lambda: DAY)
    monkeypatch.setattr(account_routes, "india_today", lambda: DAY)
    service = MobileService(
        Settings(database_path=database.path, _env_file=None),
        store,
        InvoiceCatalogue(DocumentScanner({"bills": [folder]})),
        warning=warning,
    )
    service.accounts.import_rows(
        [
            {"name": "EXAMPLE PARTY", "group": "Sundry Debtors"},
            {"name": "LOAN PARTY", "group": "Unsecured Loans"},
            {"name": "SALE ACCOUNT", "group": "Sale"},
        ]
    )
    return service, calls


def login(client: TestClient, service: MobileService) -> dict[str, str]:
    invite = service.store.invite("Example employee", "919999999999")
    session = client.post("/mobile/v1/pair", json={"invite_code": invite["invite_code"]}).json()
    return {"Authorization": "Bearer " + session["token"]}


def finished(client: TestClient, headers: dict[str, str], job_id: str) -> dict[str, Any]:
    for _ in range(100):
        row = client.get(f"/mobile/v1/reports/{job_id}", headers=headers).json()
        if row["status"] not in {"queued", "warning", "generating"}:
            return row  # type: ignore[no-any-return]
        time.sleep(0.01)
    pytest.fail("Report did not finish")


def test_group_filter_uses_name_not_parent_categories_and_reads_never_export(runtime: Any) -> None:
    service, calls = runtime
    with TestClient(create_mobile_app(service=service)) as client:
        assert client.get("/mobile/v1/account-groups").status_code == 401
        headers = login(client, service)
        groups = client.get("/mobile/v1/account-groups", headers=headers).json()
        sale = next(row for row in groups if row["name"] == "Sale")
        revenue = next(row for row in groups if row["name"] == "Revenue Accounts")
        assert (
            client.get(f"/mobile/v1/accounts?group_id={sale['id']}", headers=headers).json()[0][
                "name"
            ]
            == "SALE ACCOUNT"
        )
        assert (
            client.get(f"/mobile/v1/accounts?group_id={revenue['id']}", headers=headers).json()
            == []
        )
        assert client.get("/mobile/v1/account-reports/options", headers=headers).json() == {
            "financial_year": "26-27",
            "start_date": "2026-04-01",
            "as_of": "2026-11-07",
        }
        assert calls == []


def test_copy_account_custom_dates_idempotency_ownership_and_pdf_filename(runtime: Any) -> None:
    service, calls = runtime
    with TestClient(create_mobile_app(service=service)) as client:
        headers, other = login(client, service), login(client, service)
        account = service.accounts.accounts("EXAMPLE PARTY")[0]
        payload = {
            "account_id": account["id"],
            "start_date": "2025-01-16",
            "end_date": DAY.isoformat(),
            "request_key": "ledger-test-1",
        }
        response = client.post("/mobile/v1/account-reports/ledger", json=payload, headers=headers)
        assert response.status_code == 202
        job = finished(client, headers, response.json()["id"])
        assert job["status"] == "ready" and job["report_kind"] == "ledger"
        assert calls == ["warning", "ledger"]
        assert (
            client.post("/mobile/v1/account-reports/ledger", json=payload, headers=headers).json()[
                "id"
            ]
            == job["id"]
        )
        assert calls == ["warning", "ledger"]
        assert (
            client.post(
                "/mobile/v1/account-reports/ledger",
                json={**payload, "start_date": "2026-04-01"},
                headers=headers,
            ).status_code
            == 409
        )
        assert client.get("/mobile/v1/reports", headers=headers).json() == []
        assert (
            client.get("/mobile/v1/account-reports", headers=headers).json()[0]["id"] == job["id"]
        )
        assert client.get(f"/mobile/v1/reports/{job['id']}", headers=other).status_code == 404
        pdf = client.get(f"/mobile/v1/reports/{job['id']}/pdf", headers=headers)
        assert pdf.status_code == 200 and "EXAMPLE PARTY - Copy account.pdf" in unquote(
            pdf.headers["content-disposition"]
        )


def test_group_balances_are_verified_private_and_current_fy_only(runtime: Any) -> None:
    service, calls = runtime
    with TestClient(create_mobile_app(service=service)) as client:
        headers, other = login(client, service), login(client, service)
        group = service.accounts.group(service.accounts.group_id("Unsecured Loans"))
        payload = {"group_id": group["id"], "as_of": "2026-03-31", "request_key": "group-test-1"}
        assert (
            client.post(
                "/mobile/v1/account-reports/group-balances", json=payload, headers=headers
            ).status_code
            == 409
        )
        assert calls == []
        payload["as_of"] = DAY.isoformat()
        response = client.post(
            "/mobile/v1/account-reports/group-balances", json=payload, headers=headers
        )
        assert response.status_code == 202
        job = finished(client, headers, response.json()["id"])
        assert job["status"] == "ready" and calls == ["warning", "group"]
        url = f"/mobile/v1/reports/{job['id']}/balances"
        rows = client.get(url, headers=headers)
        assert rows.json()["credit_total"] == "123.45"
        assert client.get(url, headers=other).status_code == 404
        path = Path(service.store.job(job["id"])["pdf_path"]).parent / "balances.json"
        path.write_text("{}")
        assert client.get(url, headers=headers).status_code == 404


def test_office_cancel_prevents_new_account_exports(runtime: Any) -> None:
    service, calls = runtime
    service.warning = lambda: False
    with TestClient(create_mobile_app(service=service)) as client:
        headers = login(client, service)
        account = service.accounts.accounts("EXAMPLE")[0]
        response = client.post(
            "/mobile/v1/account-reports/ledger",
            headers=headers,
            json={
                "account_id": account["id"],
                "start_date": "2026-04-01",
                "end_date": DAY.isoformat(),
                "request_key": "cancel-ledger-1",
            },
        )
        assert finished(client, headers, response.json()["id"])["status"] == "cancelled"
        assert calls == []


def test_account_import_keeps_group_but_drops_contact_fields() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Name", "Parent Group", "Phone", "Opening balance"])
    sheet.append(["LOAN PARTY", "Unsecured Loans", "private phone", 999])
    content = BytesIO()
    workbook.save(content)
    assert account_rows(content.getvalue()) == [{"name": "LOAN PARTY", "group": "Unsecured Loans"}]


@pytest.mark.parametrize(
    "day,expected", [(date(2026, 3, 31), "25-26"), (date(2026, 4, 1), "26-27")]
)
def test_financial_year_starts_in_april(day: date, expected: str) -> None:
    assert financial_year(day)[0] == expected


@pytest.mark.parametrize("bad", ["total", "duplicate", "wrong-group"])
def test_group_excel_requires_matching_subject_and_reconciled_closing_totals(
    tmp_path: Path, bad: str
) -> None:
    workbook = Workbook()
    sheet = workbook.active
    for row in [
        ["H.S. TRADERS"],
        ["Trial Balance"],
        ["Group : Unsecured Loans"],
        ["As on 07-11-2026"],
        ["Account Name", "Debit(Rs.)", "Credit(Rs.)"],
        ["PARTY ONE", 0, 123.45],
        *([["PARTY ONE", 0, 10]] if bad == "duplicate" else []),
        ["Total", 0, 999 if bad == "total" else 123.45],
    ]:
        sheet.append(row)
    path = tmp_path / "group.xlsx"
    workbook.save(path)
    with pytest.raises(SyncError):
        parse_group_balances(
            path, "Other group" if bad == "wrong-group" else "Unsecured Loans", DAY
        )
    if bad == "wrong-group":
        result = parse_group_balances(path, "Unsecured Loans", DAY)
        assert result["credit_total"] == "123.45" and result["accounts"][0]["side"] == "Cr"


def test_copy_account_retains_opening_balance_and_only_chronological_yes(tmp_path: Path) -> None:
    exporter = CopyAccountExporter(Settings(_env_file=None), date(2026, 4, 1))
    main, root = Mock(), Mock()
    fields = [Mock() for _ in range(15)]
    exporter._main = Mock(return_value=(main, None))
    exporter._open_ledger = Mock(return_value=(root, fields))
    exporter._set = Mock(
        side_effect=lambda field, value: setattr(field.get_value, "return_value", value)
    )
    exporter._click = Mock()
    exporter._wait = Mock(return_value=root)
    exporter._export_pdf = Mock(return_value=tmp_path / "copy.pdf")
    exporter.export_ledger("EXAMPLE", DAY, tmp_path)
    assert [field.get_value() for field in fields] == [
        "STANDARD",
        "EXAMPLE",
        "01-04-2026",
        "07-11-2026",
        "Single Account (Auto)",
        "Name",
        *(["N"] * 8),
        "Y",
    ]


def test_group_options_match_owner_screenshot() -> None:
    exporter = GroupBalancesExporter(Settings(_env_file=None))
    fields = [Mock() for _ in range(7)]
    exporter._edits = Mock(return_value=fields)
    exporter._set = Mock(
        side_effect=lambda field, value: setattr(field.get_value, "return_value", value)
    )
    exporter._options(Mock(), "Sale", DAY)
    assert [field.get_value() for field in fields] == [
        "Sale",
        "07-11-2026",
        "Name",
        "N",
        "N",
        "Not Required",
        "N",
    ]


def test_account_pdf_rejects_wrong_subject_or_report_date(tmp_path: Path) -> None:
    path = tmp_path / "copy.pdf"
    make_pdf(
        path,
        "H.S. TRADERS\nBranch: S.NO. 17 Example Lane\nAccount Ledger\nAccount : EXAMPLE\n"
        "From 01-04-2026 to 07-11-2026\nVch/Bill No\n08-11-2026",
    )
    assert verify_account_pdf(path, "EXAMPLE", DAY, date(2026, 4, 1))["pages"] == 1
    with pytest.raises(SyncError):
        verify_account_pdf(path, "OTHER", DAY, date(2026, 4, 1))
    with pytest.raises(SyncError):
        verify_account_pdf(path, "EXAMPLE", date(2026, 11, 8), date(2026, 4, 1))


def test_ledger_subject_must_match_the_whole_account_name(tmp_path: Path) -> None:
    path = tmp_path / "copy.pdf"
    make_pdf(
        path,
        "H.S. TRADERS\nAccount Ledger\nAccount : EXAMPLE LIMITED\n"
        "From 01-04-2026 to 07-11-2026\nDate\nType\nVch/Bill No",
    )
    with pytest.raises(SyncError):
        verify_account_pdf(path, "EXAMPLE", DAY, date(2026, 4, 1))


def test_report_queue_is_shared_between_outstanding_and_copy_account(runtime: Any) -> None:
    service, calls = runtime
    user = service.store.invite("Employee", "919999999999")
    party = service.store.parties()[0]
    service.store.create_job(
        user["id"],
        party,
        DAY.isoformat(),
        "queued-ledger-1",
        report_kind="ledger",
        parameters={"start_date": "2026-04-01"},
    )
    with pytest.raises(ValueError, match="still being prepared"):
        service.submit(user["id"], party["id"], DAY, "outstanding-2")
    assert calls == []
    service.close()


def test_new_columns_migrate_old_jobs_without_reclassifying_them(tmp_path: Path) -> None:
    database = Database(tmp_path / "office.db")
    database.initialize()
    with closing(database.connect()) as db, db:
        db.executescript(MOBILE_SCHEMA)
        db.execute(
            "INSERT INTO mobile_users VALUES ('old-user','Employee','919999999999',1,'2026-11-07')"
        )
        db.execute(
            "INSERT INTO mobile_jobs(id,user_id,request_key,party_id,party_name,as_of,"
            "status,created_at) VALUES "
            "('old-job','old-user','old-key','party','Example','2026-11-07','ready','2026-11-07')"
        )
    store = MobileStore(database)
    assert store.job("old-job")["report_kind"] == "outstanding"
    assert store.public(store.job("old-job"))["parameters"] == {}
    assert store.jobs("old-user", "ledger") == []


def test_group_excel_is_removed_when_parsing_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exporter = GroupBalancesExporter(Settings(_env_file=None))
    main, root = Mock(), Mock()
    main.window_text.return_value = "Busy 21 | H.S. TRADERS (F.Y. 2026-27)"
    exporter._main = Mock(return_value=(main, None))
    exporter._home = Mock(return_value=True)
    exporter._guard = Mock(return_value=[root])
    exporter._wait = Mock(return_value=root)
    exporter._click = Mock()
    exporter._options = Mock()
    saved: list[Path] = []

    def excel(main: Any, desktop: Any, target: Any, filename: Path) -> None:
        saved.append(filename)
        filename.write_bytes(b"incomplete export")

    exporter._excel = excel  # type: ignore[method-assign]
    monkeypatch.setattr(account_reports, "india_today", lambda: DAY)
    monkeypatch.setattr(
        account_reports, "parse_group_balances", Mock(side_effect=SyncError("Invalid export"))
    )
    with pytest.raises(SyncError, match="Invalid export"):
        exporter.export_group("Sale", DAY, tmp_path)
    assert saved and not saved[0].exists() and not saved[0].parent.exists()


def test_group_pdf_repeats_subject_and_date_without_losing_balances(tmp_path: Path) -> None:
    rows = [
        {"name": f"Example account {i}", "debit": "0.00", "credit": "100.00"} for i in range(80)
    ]
    snapshot = {
        "group_name": "Example group",
        "as_of": "2026-11-07",
        "accounts": rows,
        "account_count": 80,
        "debit_total": "0.00",
        "credit_total": "8000.00",
    }
    path = tmp_path / "group.pdf"
    render_group_pdf(snapshot, path)
    with pymupdf.open(path) as document:
        assert len(document) > 1
        for page in document:
            assert "Example group" in page.get_text() and "07-11-2026" in page.get_text()
        text = "\n".join(page.get_text() for page in document)
        assert "8,000.00" in text and "Example account 79" in text
    assert verify_account_pdf(path, "Example group", DAY)["pages"] > 1
