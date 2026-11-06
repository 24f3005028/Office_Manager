"""All-account data correctness, isolation, expiry and cancelled desktop work."""

from datetime import date
from pathlib import Path

import pymupdf
import pytest
from app.config import Settings
from app.db import Database
from app.domains.documents.scanner import DocumentScanner
from app.domains.mobile.all_outstanding import ALL_ID, parse_all_outstanding, verify_all_pdf
from app.domains.mobile.invoices import InvoiceCatalogue
from app.domains.mobile.service import MobileService
from app.domains.mobile.store import MobileStore
from app.domains.pouncha_sync.parser import SyncError
from app.mobile_main import create_mobile_app
from fastapi.testclient import TestClient
from openpyxl import Workbook

DAY = date(2026, 11, 6)


def excel(path: Path, *, total: float = 150.0, summary: bool = False, duplicate: bool = False):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["H.S. TRADERS"])
    sheet.append(["Bills Receivable"])
    sheet.append(["All Accounts"])
    sheet.append(["From 16-01-2025 to 06-11-2026", "Bills Status as on : 06-11-2026"])
    if summary:
        sheet.append(["Account", "Pending Amt."])
        sheet.append(["PARTY A", 100])
        sheet.append(["PARTY B", 50])
        sheet.append(["Grand Total", total])
    else:
        sheet.append(
            ["Account", "Dated", "Ref. No.", "Ref. Amt.", "Pending Amt.", "Due Date", "Due Days"]
        )
        sheet.append(["PARTY A", "01-11-2026", "HST/26-27/1", 200, 100, "01-11-2026", 5])
        sheet.append(["PARTY B", "02-11-2026", "HST/26-27/2", 50, 50, "02-11-2026", 4])
        if duplicate:
            sheet.append(["PARTY B", "02-11-2026", "HST/26-27/2", 50, 50, "02-11-2026", 4])
        sheet.append(["Grand Total", None, None, 250, total])
    workbook.save(path)


def pdf(path: Path, total: str = "150.00"):
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text(
            (30, 40),
            "H.S. TRADERS\nBills Receivable\nAll Accounts\nFrom 16-1-2025 to 6-11-2026\n"
            "Bills Status as on : 6-11-2026\nPARTY A\nPARTY B\nGrand Total 250.00 " + total,
        )
        document.save(path)


def test_detailed_and_summary_exports_match_their_totals(tmp_path):
    path = tmp_path / "export.xlsx"
    excel(path)
    detailed = parse_all_outstanding(path, DAY)
    assert detailed["pending_amount"] == "150.00"
    assert detailed["bill_count"] == 2
    assert detailed["accounts"][0]["bills"][0]["pending_amount"] == "100.00"
    excel(path, summary=True)
    summary = parse_all_outstanding(path, DAY)
    assert summary["bill_count"] is None and summary["layout"] == "summary"
    assert summary["account_count"] == 2


@pytest.mark.parametrize("kind", ["total", "duplicate", "date", "company", "missing_party"])
def test_inconsistent_reports_are_never_shared(tmp_path, kind):
    path = tmp_path / "bad.xlsx"
    excel(path, total=999 if kind == "total" else 150, duplicate=kind == "duplicate")
    if kind in {"company", "missing_party"}:
        from openpyxl import load_workbook

        workbook = load_workbook(path)
        sheet = workbook.active
        if kind == "company":
            sheet["A1"] = "OTHER COMPANY"
        else:
            sheet["A6"] = None
        workbook.save(path)
    with pytest.raises(SyncError):
        parse_all_outstanding(path, date(2026, 11, 5) if kind == "date" else DAY)


def test_pdf_and_app_totals_must_match(tmp_path):
    path = tmp_path / "export.xlsx"
    excel(path)
    snapshot = parse_all_outstanding(path, DAY)
    output = tmp_path / "all.pdf"
    pdf(output)
    assert verify_all_pdf(output, snapshot, DAY)["pending_amount"] == "150.00"
    output.unlink()
    pdf(output, "149.00")
    with pytest.raises(SyncError, match="total"):
        verify_all_pdf(output, snapshot, DAY)


@pytest.fixture
def runtime(tmp_path):
    db = Database(tmp_path / "office.sqlite3")
    db.initialize()
    store = MobileStore(db)
    service = MobileService(
        Settings(database_path=db.path, _env_file=None),
        store,
        InvoiceCatalogue(DocumentScanner({"bills": []})),
        warning=lambda: True,
    )
    # Execute explicitly in the tests instead of touching the Windows desktop.
    service.pool.submit = lambda *args: None

    class Exporter:
        def export_all(self, as_of, directory):
            xlsx = tmp_path / "export.xlsx"
            excel(xlsx)
            snapshot = parse_all_outstanding(xlsx, as_of)
            path = directory / "All accounts outstanding.pdf"
            pdf(path)
            return path, snapshot

    service.all_exporter = Exporter()
    with TestClient(create_mobile_app(service=service)) as client:
        users = []
        for name in ["First", "Second"]:
            invite = store.invite(name, "919999999999")
            token = store.pair(invite["invite_code"])
            users.append((invite["id"], {"Authorization": "Bearer " + token["token"]}))
        yield client, service, users


def test_all_account_creation_is_manual_idempotent_and_owner_scoped(runtime):
    client, service, users = runtime
    payload = {"as_of": DAY.isoformat(), "request_key": "all-accounts-test"}
    assert client.post("/mobile/v1/outstanding/all", json=payload).status_code == 401
    row = client.post("/mobile/v1/outstanding/all", json=payload, headers=users[0][1]).json()
    assert row["party_id"] == ALL_ID and row["status"] == "queued"
    assert (
        client.post("/mobile/v1/outstanding/all", json=payload, headers=users[0][1]).json()["id"]
        == row["id"]
    )
    service.execute(row["id"])
    url = f"/mobile/v1/reports/{row['id']}/outstanding"
    result = client.get(url, headers=users[0][1])
    assert result.status_code == 200 and result.json()["account_count"] == 2
    assert client.get(url, headers=users[1][1]).status_code == 404
    assert client.get(url).status_code == 401
    report = service.store.job(row["id"])
    (Path(report["pdf_path"]).parent / "outstanding.json").write_text("{}")
    assert client.get(url, headers=users[0][1]).status_code == 404


def test_warning_cancellation_never_exports(runtime):
    client, service, users = runtime
    service.warning = lambda: False
    service.all_exporter.export_all = lambda *args: pytest.fail("No BUSY export after cancellation")
    row = client.post(
        "/mobile/v1/outstanding/all",
        json={"as_of": DAY.isoformat(), "request_key": "cancel-all-accounts"},
        headers=users[0][1],
    ).json()
    service.execute(row["id"])
    assert service.store.job(row["id"])["status"] == "cancelled"


def test_new1_indented_subtotals_and_zero_spacers_are_not_counted_as_bills(tmp_path):
    path = tmp_path / "new1.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    for row in [
        ["H.S. TRADERS"],
        ["Bills Receivable"],
        ["All Accounts"],
        ["From 16-1-2025 to 6-11-2026", "Bills Status as on : 6-11-2026"],
        [
            "Account",
            "BROKER",
            "Dated",
            "Type",
            "Ref. No.",
            "Ref. Amt.",
            "Pending Amt.",
            "DISCOUNT",
            "Due",
            "Due Date",
            "Due Days",
        ],
        [
            "PARTY A",
            "BROKER A",
            "01-11-2026",
            "Sale",
            "HST/26-27/1",
            200,
            100,
            5,
            "Y",
            "01-11-2026",
            5,
        ],
        [None, None, "02-11-2026", "Sale", "HST/26-27/2", 50, 50, 0, "Y", "02-11-2026", 4],
        [None, None, None, None, "    Total", 250, 150, 0, None, None, 0],
        [None, None, None, None, None, 0, 0, 0, None, None, 0],
        [None, None, None, None, "Total", 250, 150],
    ]:
        sheet.append(row)
    workbook.save(path)
    snapshot = parse_all_outstanding(path, DAY)
    assert snapshot["account_count"] == 1 and snapshot["bill_count"] == 2
    assert snapshot["accounts"][0]["bills"][1]["broker"] == "BROKER A"
    assert snapshot["accounts"][0]["bills"][0]["discount"] == "5"
    sheet["G8"] = 149
    workbook.save(path)
    with pytest.raises(SyncError, match="subtotal"):
        parse_all_outstanding(path, DAY)


def test_all_account_options_match_the_confirmed_new1_screen():
    from types import SimpleNamespace

    from app.domains.mobile.all_outstanding import AllAccountsExporter

    class Field:
        def __init__(self, left, top):
            self.left, self.top, self.value = left, top, ""

        def rectangle(self):
            return SimpleNamespace(left=self.left, top=self.top)

        def set_edit_text(self, value):
            self.value = value

        def get_value(self):
            return self.value

    left = [Field(100, i * 30) for i in range(8)]
    right = [Field(600, i * 30) for i in range(10)]
    exporter = AllAccountsExporter(Settings(_env_file=None))
    exporter._edits = lambda _: left + right
    exporter._configure_options(None, DAY)
    assert [field.value for field in left] == [
        "new1",
        "N",
        "N",
        "Pending",
        "16-01-2025",
        "06-11-2026",
        "06-11-2026",
        "Name",
    ]
    assert [field.value for field in right] == ["Y", "0", "N", "N", "N", "N", "N", "N", "N", "D"]
