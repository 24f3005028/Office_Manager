"""Read-only All Account / new1 export and verified structured outstanding data."""

from __future__ import annotations

import importlib
import re
import sys
import time
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from zipfile import ZipFile

import pymupdf
from openpyxl import load_workbook  # type: ignore[import-untyped]

from app.domains.mobile.outstanding_pdf import render_all_pdf
from app.domains.mobile.reports import REPORT_START, OutstandingExporter
from app.domains.pouncha_sync.busy import normalize
from app.domains.pouncha_sync.parser import SyncError, parse_date

ALL_ID = "all-accounts"
ALL_NAME = "All accounts outstanding"


def money(value: Any) -> Decimal:
    try:
        raw = str(value).strip().replace(",", "")
        if raw.startswith("(") and raw.endswith(")"):
            raw = "-" + raw[1:-1]
        number = Decimal(raw)
        if not number.is_finite():
            raise InvalidOperation
        return number.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise SyncError("An outstanding amount could not be read safely.") from exc


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def _metadata(text: str, as_of: date) -> None:
    if (
        "hstraders" not in _key(text)
        or "billsreceivable" not in _key(text)
        or "allaccounts" not in _key(text)
    ):
        raise SyncError("The export is not an H.S. TRADERS Bills Receivable report.")
    periods = list(
        re.finditer(
            r"From\s+(\d{1,2}[-/]\d{1,2}[-/]\d{4})\s+to\s+(\d{1,2}[-/]\d{1,2}[-/]\d{4})", text, re.I
        )
    )
    statuses = list(
        re.finditer(r"Bills Status as on\s*:\s*(\d{1,2}[-/]\d{1,2}[-/]\d{4})", text, re.I)
    )
    if (
        not periods
        or not statuses
        or any(
            parse_date(period[1]) != REPORT_START or parse_date(period[2]) != as_of
            for period in periods
        )
        or any(parse_date(status[1]) != as_of for status in statuses)
    ):
        raise SyncError("The all-account report period or bills-status date did not match.")


def parse_all_outstanding(path: Path, as_of: date) -> dict[str, Any]:
    if not path.is_file() or not 0 < path.stat().st_size <= 25 * 1024 * 1024:
        raise SyncError("BUSY did not create a usable all-account Excel export.")
    try:
        with ZipFile(path) as archive:
            if sum(item.file_size for item in archive.infolist()) > 100 * 1024 * 1024:
                raise SyncError("The all-account workbook is too large to process safely.")
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            sheet = workbook.worksheets[0]
            if (sheet.max_row or 0) > 100000 or (sheet.max_column or 0) > 64:
                raise SyncError("The all-account workbook exceeds the supported report size.")
            rows = list(sheet.iter_rows(max_col=64, values_only=True))
        finally:
            workbook.close()
    except SyncError:
        raise
    except Exception as exc:
        raise SyncError("The all-account Excel export could not be read.") from exc
    aliases = {
        "party": {"account", "accountname", "party", "partyname"},
        "pending": {"pendingamt", "pendingamount", "outstandingamount", "outstandingamt"},
        "bill": {"refno", "referenceno", "billno", "vchbillno", "billnumber"},
        "date": {"dated", "date", "billdate"},
        "due": {"duedate"},
        "days": {"duedays", "dueday"},
        "amount": {"refamt", "refamount", "billamount"},
        "type": {"type"},
        "broker": {"broker"},
        "discount": {"discount"},
    }
    columns: dict[str, int] = {}
    header = -1
    for index, row in enumerate(rows[:80]):
        keys = [_key(value) for value in row]
        found = {
            name: next((i for i, key in enumerate(keys) if key in choices), -1)
            for name, choices in aliases.items()
        }
        if found["party"] >= 0 and found["pending"] >= 0:
            columns, header = found, index
            break
    if header < 0:
        raise SyncError(
            "new1 must export an Account/Party column and Pending Amt. column. "
            "No values were guessed."
        )
    _metadata(" ".join(str(v) for row in rows[:header] for v in row if v is not None), as_of)
    detailed = columns["bill"] >= 0
    if detailed and columns["date"] < 0:
        raise SyncError("The all-account bill-date column is missing.")
    accounts: dict[str, dict[str, Any]] = {}
    seen: set[tuple[str, str, str, str]] = set()
    last_party = ""
    grand: Decimal | None = None
    for row in rows[header + 1 :]:

        def cell(name: str, row: Any = row) -> Any:
            return row[columns[name]] if columns[name] >= 0 else None

        raw_party = str(cell("party") or "").strip()
        values = [str(v).strip() for v in row if v is not None and str(v).strip()]
        if not values:
            continue
        total_label = next(
            (
                str(value)
                for value in row
                if isinstance(value, str)
                and _key(value) in {"total", "grandtotal", "subtotal", "accounttotal", "partytotal"}
            ),
            None,
        )
        if total_label is not None and (
            _key(total_label) in {"subtotal", "accounttotal", "partytotal"}
            or total_label != total_label.lstrip()
        ):
            if last_party and money(cell("pending")) != Decimal(
                accounts[last_party]["pending_amount"]
            ):
                raise SyncError("A party subtotal does not match its outstanding bills.")
            if not last_party:
                raise SyncError("A party subtotal appeared without its account rows.")
            last_party = ""
            continue
        if total_label is not None:
            grand = money(cell("pending"))
            continue
        if _key(raw_party) in aliases["party"]:
            continue
        if cell("pending") is None or str(cell("pending")).strip() == "":
            continue
        if detailed and not raw_party and cell("date") in (None, "") and cell("bill") in (None, ""):
            numeric = [value for value in row if isinstance(value, (int, float, Decimal))]
            if (
                numeric
                and all(money(value) == 0 for value in numeric)
                and all(
                    value is None
                    or isinstance(value, (int, float, Decimal))
                    or not str(value).strip()
                    for value in row
                )
            ):
                continue
            raise SyncError("An unrecognised numeric footer appeared in the outstanding report.")
        party = raw_party or (last_party if detailed else "")
        if not party or len(party) > 200 or any(ord(c) < 32 for c in party):
            raise SyncError(
                "A report row has no valid party name. It was not assigned to another account."
            )
        last_party = party
        pending = money(cell("pending"))
        account = accounts.setdefault(
            party, {"party_name": party, "pending_amount": "0.00", "bills": []}
        )
        if cell("broker") not in (None, ""):
            account["broker"] = str(cell("broker")).strip()
        if detailed:
            bill = str(cell("bill") or "").strip()
            if not bill:
                raise SyncError("An outstanding bill reference is missing.")
            dated = parse_date(cell("date"))
            if not REPORT_START <= dated <= as_of:
                raise SyncError("An outstanding bill date falls outside the requested period.")
            kind = str(cell("type") or "").strip()
            key = (party, bill, dated.isoformat(), kind)
            if key in seen:
                raise SyncError("The all-account export contains duplicate bill rows.")
            seen.add(key)
            due = parse_date(cell("due")).isoformat() if cell("due") not in (None, "") else None
            days = int(cell("days")) if cell("days") not in (None, "") else None
            account["bills"].append(
                {
                    "bill_number": bill,
                    "date": dated.isoformat(),
                    "type": kind,
                    "pending_amount": str(pending),
                    "reference_amount": str(money(cell("amount")))
                    if cell("amount") not in (None, "")
                    else None,
                    "due_date": due,
                    "due_days": days,
                    "broker": account.get("broker"),
                    "discount": str(cell("discount")) if cell("discount") is not None else None,
                }
            )
        elif account["pending_amount"] != "0.00":
            raise SyncError("The summary contains repeated party rows; its meaning is ambiguous.")
        account["pending_amount"] = str(Decimal(account["pending_amount"]) + pending)
    total = sum(
        (Decimal(account["pending_amount"]) for account in accounts.values()), Decimal("0.00")
    )
    if grand is None or grand != total:
        raise SyncError(
            "The all-account total does not match the exported rows. It was not shared."
        )
    return {
        "company_header": [
            str(next(value for value in row if value is not None)).strip()
            for row in rows[:header]
            if any(value is not None for value in row)
            and _key(next(value for value in row if value is not None))
            not in {"billsreceivable", "allaccounts"}
            and not any(
                "from " in str(value).casefold() or "bills status" in str(value).casefold()
                for value in row
            )
        ][:6],
        "scope": "all",
        "format": "new1",
        "as_of": as_of.isoformat(),
        "start_date": REPORT_START.isoformat(),
        "pending_amount": str(total),
        "account_count": len(accounts),
        "bill_count": len(seen) if detailed else None,
        "layout": "bills" if detailed else "summary",
        "accounts": sorted(accounts.values(), key=lambda item: item["party_name"].casefold()),
    }


def verify_all_pdf(path: Path, snapshot: dict[str, Any], as_of: date) -> dict[str, Any]:
    if not path.is_file() or not 0 < path.stat().st_size <= 25 * 1024 * 1024:
        raise SyncError("BUSY did not save a usable all-account PDF.")
    with pymupdf.open(path) as document:  # type: ignore[no-untyped-call]
        if document.is_encrypted or not document.page_count:
            raise SyncError("The all-account PDF is empty or locked.")
        text = "\n".join(str(page.get_text()) for page in document)
        pages = document.page_count
    _metadata(text, as_of)
    if any(
        normalize(account["party_name"]) not in normalize(text) for account in snapshot["accounts"]
    ):
        raise SyncError("A party is missing from the PDF. It was not shared.")
    totals = list(
        re.finditer(
            r"(?:Grand\s+Total|(?<!\w)Total)\s*:?\s*((?:-?[\d,]+\.\d{2}\s*){1,3})", text, re.I
        )
    )
    if not totals or money(re.findall(r"-?[\d,]+\.\d{2}", totals[-1][1])[-1]) != Decimal(
        snapshot["pending_amount"]
    ):
        raise SyncError(
            "The PDF total does not match the in-app outstanding view. It was not shared."
        )
    return {key: value for key, value in snapshot.items() if key != "accounts"} | {"pages": pages}


class AllAccountsExporter(OutstandingExporter):
    def export_all(self, as_of: date, directory: Path) -> tuple[Path, dict[str, Any]]:
        if sys.platform != "win32":
            raise SyncError("An unlocked Windows desktop is required for BUSY reports.")
        desktop = importlib.import_module("pywinauto").Desktop(backend="uia")
        windows = desktop.windows(title_re=r"(?i)^Busy\s+21\s+Rel\b.*", visible_only=True)
        if len(windows) != 1:
            raise SyncError("Open one BUSY 21 company window before requesting this report.")
        main = windows[0]
        company = re.search(r"\|\s*([^|]+?)\s*\(F\.Y\.", main.window_text(), re.I)
        if company is None or normalize(company[1]) != normalize(self.settings.pouncha_company):
            raise SyncError("BUSY must be logged into H.S. TRADERS.")
        if not self._home(main, desktop):
            raise SyncError("BUSY did not reach its company homepage safely.")
        self._guard(main, desktop)[0].type_keys("%f", pause=0.2)
        self._guard(main, desktop)[0].type_keys("o{ENTER}", pause=0.2)
        target = self._wait(main, desktop, lambda root: bool(self._buttons(root, "All Account")))
        self._click(target, "All Account")
        target = self._wait(main, desktop, lambda root: len(self._edits(root)) == 18)
        fields = self._edits(target)
        self._set(fields[0], "new1")
        fields[0].type_keys("{TAB}", pause=0.2)
        target = self._wait(main, desktop, lambda root: len(self._edits(root)) == 18)
        self._configure_options(target, as_of)
        self._click(target, r"OK\s*\(F2\)")
        target = self._wait(
            main, desktop, self._is_report, self.settings.pouncha_export_timeout_seconds
        )
        with TemporaryDirectory(prefix="all-outstanding-") as temp:
            excel = Path(temp) / "all-accounts.xlsx"
            target.type_keys("%e", pause=0.2)
            dialog = self._wait(
                main,
                desktop,
                lambda root: bool(
                    re.fullmatch(r"Export (?:Report )?Data", root.window_text(), re.I)
                ),
            )
            dialog = self._prepare_excel_export(main, desktop, dialog, excel)
            self._click(dialog, "OK")
            previous = -1
            stable = 0
            deadline = time.monotonic() + self.settings.pouncha_export_timeout_seconds
            while time.monotonic() < deadline:
                for window in self._guard(main, desktop):
                    if re.search("Open File Now", window.window_text(), re.I):
                        self._click(window, "No")
                if excel.is_file():
                    size = excel.stat().st_size
                    stable = stable + 1 if size > 0 and size == previous else 0
                    previous = size
                    if stable >= 3:
                        break
                time.sleep(0.4)
            if stable < 3:
                raise SyncError("BUSY did not finish its all-account Excel export.")
            snapshot = parse_all_outstanding(excel, as_of)
        path = directory / "All accounts outstanding.pdf"
        render_all_pdf(
            snapshot, path, self.settings.database_path.parent / "mobile-outstanding-template.json"
        )
        verify_all_pdf(path, snapshot, as_of)
        return path, snapshot

    def _configure_options(self, target: Any, as_of: date) -> None:
        fields = self._edits(target)
        middle = (
            min(e.rectangle().left for e in fields) + max(e.rectangle().left for e in fields)
        ) / 2
        left = sorted(
            [e for e in fields if e.rectangle().left < middle], key=lambda e: e.rectangle().top
        )
        right = sorted(
            [e for e in fields if e.rectangle().left >= middle], key=lambda e: e.rectangle().top
        )
        if len(left) != 8 or len(right) != 10:
            raise SyncError("All Account / new1 options changed. Check its layout at the office.")
        day = as_of.strftime("%d-%m-%Y")
        values = [
            "new1",
            "N",
            "N",
            "Pending",
            "16-01-2025",
            day,
            day,
            "Name",
            "Y",
            "0",
            *("N" for _ in range(7)),
            "D",
        ]
        for field, value in zip(left + right, values, strict=True):
            self._set(field, value)
        if [field.get_value().strip().casefold() for field in left + right] != [
            value.casefold() for value in values
        ]:
            raise SyncError("BUSY did not retain the All Account / new1 report options.")
