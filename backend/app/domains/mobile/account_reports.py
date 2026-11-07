"""On-demand account ledgers and named-group closing balances from BUSY reports."""

from __future__ import annotations

import importlib
import re
import sys
import time
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from zoneinfo import ZoneInfo

import pymupdf
from openpyxl import load_workbook  # type: ignore[import-untyped]

from app.config import Settings
from app.domains.mobile.group_pdf import render_group_pdf
from app.domains.mobile.reports import OutstandingExporter, statement_filename
from app.domains.pouncha_sync.busy import normalize
from app.domains.pouncha_sync.parser import SyncError


def india_today() -> date:
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


def financial_year(day: date) -> tuple[str, date, date]:
    year = day.year if day.month >= 4 else day.year - 1
    return f"{year % 100:02d}-{(year + 1) % 100:02d}", date(year, 4, 1), date(year + 1, 3, 31)


def report_filename(job: dict[str, Any]) -> str:
    suffix = {"ledger": " - Copy account", "group_balances": " - Closing balances"}.get(
        job.get("report_kind", ""), ""
    )
    return statement_filename(job["party_name"] + suffix)


def _dates(text: str) -> set[date]:
    result = set()
    for a, b, c in re.findall(r"\b(\d{1,4})[-/](\d{1,2})[-/](\d{1,4})\b", text):
        try:
            result.add(
                date(int(a), int(b), int(c)) if len(a) == 4 else date(int(c), int(b), int(a))
            )
        except ValueError:
            continue
    return result


def _subject(text: str, name: str) -> bool:
    pattern = r"\s+".join(re.escape(part) for part in name.split())
    return bool(re.search(r"(?<!\w)" + pattern + r"(?!\w)", text, re.I))


def verify_account_pdf(
    path: Path, subject: str, end: date, start: date | None = None
) -> dict[str, Any]:
    if not path.is_file() or not 0 < path.stat().st_size <= 25 * 1024 * 1024:
        raise SyncError("BUSY did not create a usable account PDF.")
    with pymupdf.open(path) as document:  # type: ignore[no-untyped-call]
        if document.is_encrypted or not document.page_count:
            raise SyncError("The account PDF is empty or locked.")
        first = str(document[0].get_text())
        pages = document.page_count
    # Report heading precedes the table's debit/credit columns, so transaction dates
    # cannot stand in for the requested report dates during verification.
    header_lines: list[str] = []
    for line in first.splitlines():
        if normalize(line) in {
            "ACCOUNT",
            "ACCOUNTNAME",
            "DATE",
            "DATED",
            "SNO",
            "VCHBILLNO",
            "DEBITRS",
            "CREDITRS",
            "DEBITBAL",
            "CREDITBAL",
        } or re.search(r"^(?:Date|Dated|Vch/Bill No|S\.?No\.?)(?:$|\s)", line.strip(), re.I):
            break
        header_lines.append(line)
    header = "\n".join(header_lines)
    title = r"Account\s+Ledger" if start is not None else r"Trial\s+Balance|Closing\s+Balance"
    subject_match = re.search(
        r"\bAccount\s*:\s*(.*?)\s+From\b"
        if start is not None
        else r"\bGroup\s*:\s*(.*?)\s+As\s+on\b",
        header,
        re.I | re.S,
    )
    matches_subject = bool(
        subject_match
        and " ".join(subject_match[1].split()).casefold() == " ".join(subject.split()).casefold()
    )
    date_text = r"(\d{1,2}[-/]\d{1,2}[-/]\d{4})"
    range_match = re.search(r"\bFrom\s*:?\s*" + date_text + r"\s+to\s+" + date_text, header, re.I)
    status_match = re.search(r"\bAs\s+on\s*:?\s*" + date_text, header, re.I)
    matches_dates = (
        bool(range_match and _dates(range_match[1]) == {start} and _dates(range_match[2]) == {end})
        if start is not None
        else bool(status_match and _dates(status_match[1]) == {end})
    )
    if (
        not re.search(title, header, re.I)
        or normalize(first.splitlines()[0]) != "HSTRADERS"
        or not matches_subject
        or not matches_dates
    ):
        raise SyncError(
            "The account PDF name or dates did not match the request. It was not shared."
        )
    return {
        "pages": pages,
        "as_of": end.isoformat(),
        "start_date": start.isoformat() if start else None,
    }


def _money(value: Any) -> Decimal:
    if value is None or str(value).strip() in {"", "-", "--"}:
        return Decimal("0.00")
    text = re.sub(r"(?:Rs\.?|₹|,|\s)", "", str(value), flags=re.I)
    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", text):
        raise SyncError("A closing balance amount could not be read safely.")
    try:
        return Decimal(text).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise SyncError("A closing balance amount is invalid.") from exc


def parse_group_balances(path: Path, group: str, as_of: date) -> dict[str, Any]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.active
        if sheet is None or sheet.max_row > 50000 or sheet.max_column > 100:
            raise SyncError("The group balance export is empty or too large.")
        columns: tuple[int, int, int] | None = None
        heading: list[str] = []
        declared_groups: list[str] = []
        status_dates: set[date] = set()
        accounts = []
        seen: set[str] = set()
        total: tuple[Decimal, Decimal] | None = None
        for raw in sheet.iter_rows(values_only=True):
            values = [
                value.strftime("%d-%m-%Y") if isinstance(value, (date, datetime)) else value
                for value in raw
            ]
            labels = [normalize(str(value or "")) for value in values]
            if columns is None:
                names = [
                    i
                    for i, value in enumerate(labels)
                    if value in {"ACCOUNT", "ACCOUNTNAME", "NAME", "PARTICULARS"}
                ]
                debits = [
                    i
                    for i, value in enumerate(labels)
                    if value
                    in {
                        "DEBIT",
                        "DEBITRS",
                        "DEBITBAL",
                        "DEBITRSAMOUNT",
                        "CLOSINGBALANCEDR",
                        "CLOSINGBALDR",
                        "CLOSINGBALANCEDEBIT",
                    }
                ]
                credits = [
                    i
                    for i, value in enumerate(labels)
                    if value
                    in {
                        "CREDIT",
                        "CREDITRS",
                        "CREDITBAL",
                        "CREDITRSAMOUNT",
                        "CLOSINGBALANCECR",
                        "CLOSINGBALCR",
                        "CLOSINGBALANCECREDIT",
                    }
                ]
                if len(names) == len(debits) == len(credits) == 1:
                    columns = names[0], debits[0], credits[0]
                else:
                    heading.append(" ".join(str(value or "") for value in values))
                    for value in values:
                        group_match = re.fullmatch(
                            r"\s*Group\s*:\s*(.+?)\s*", str(value or ""), re.I
                        )
                        if group_match:
                            declared_groups.append(" ".join(group_match[1].split()).casefold())
                        if re.search(r"\bAs\s+On\b", str(value or ""), re.I):
                            status_dates.update(_dates(str(value)))
                continue
            name = str(values[columns[0]] or "").strip()
            if not name or normalize(name) in {"ACCOUNT", "ACCOUNTNAME", "NAME", "PARTICULARS"}:
                continue
            debit, credit = _money(values[columns[1]]), _money(values[columns[2]])
            if normalize(name) in {"TOTAL", "GRANDTOTAL"}:
                total = debit, credit
                continue
            if total is not None:
                if debit or credit:
                    raise SyncError("Unexpected amounts follow the group report total.")
                continue
            if not debit and not credit:
                continue
            if debit and credit or name.casefold() in seen:
                raise SyncError("The group export contains ambiguous or repeated closing balances.")
            seen.add(name.casefold())
            accounts.append(
                {
                    "name": name,
                    "debit": str(debit),
                    "credit": str(credit),
                    "balance": str(debit or credit),
                    "side": "Dr" if debit else "Cr",
                }
            )
        debit_total = sum((Decimal(row["debit"]) for row in accounts), Decimal("0.00"))
        credit_total = sum((Decimal(row["credit"]) for row in accounts), Decimal("0.00"))
        text = " ".join(heading)
        if (
            columns is None
            or declared_groups != [" ".join(group.split()).casefold()]
            or status_dates != {as_of}
            or "HSTRADERS" not in normalize(text)
            or "TRIALBALANCE" not in normalize(text)
        ):
            raise SyncError(
                "The group export name, date or closing-balance columns could not be verified."
            )
        if total is None or total != (debit_total, credit_total):
            raise SyncError("The group closing balances do not reconcile to BUSY's total.")
        return {
            "group_name": group,
            "as_of": as_of.isoformat(),
            "accounts": accounts,
            "account_count": len(accounts),
            "debit_total": str(debit_total),
            "credit_total": str(credit_total),
        }
    finally:
        workbook.close()


class AccountReportExporter(OutstandingExporter):
    def _main(self) -> tuple[Any, Any]:
        if sys.platform != "win32":
            raise SyncError("An unlocked Windows desktop is required for account reports.")
        desktop = importlib.import_module("pywinauto").Desktop(backend="uia")
        windows = desktop.windows(title_re=r"(?i)^Busy\s+21\s+Rel\b.*", visible_only=True)
        if len(windows) != 1:
            raise SyncError("Open one BUSY 21 company window before requesting an account report.")
        main = windows[0]
        company = re.search(r"\|\s*([^|]+?)\s*\(F\.Y\.", main.window_text(), re.I)
        if company is None or normalize(company[1]) != normalize(self.settings.pouncha_company):
            raise SyncError("BUSY must be logged into H.S. TRADERS.")
        return main, desktop

    def _excel(self, main: Any, desktop: Any, target: Any, filename: Path) -> None:
        target.type_keys("%e", pause=0.2)
        dialog = self._wait(
            main,
            desktop,
            lambda root: bool(re.fullmatch(r"Export (?:Report )?Data", root.window_text(), re.I)),
        )
        dialog = self._prepare_excel_export(main, desktop, dialog, filename)
        self._click(dialog, "OK")
        previous, stable = -1, 0
        deadline = time.monotonic() + self.settings.pouncha_export_timeout_seconds
        while time.monotonic() < deadline:
            for window in self._guard(main, desktop):
                if re.search("Open File Now", window.window_text(), re.I):
                    self._click(window, "No")
            if filename.is_file():
                size = filename.stat().st_size
                stable = stable + 1 if size > 0 and size == previous else 0
                previous = size
                if stable >= 3:
                    return
            time.sleep(0.4)
        raise SyncError("BUSY did not finish the group balance export.")


class CopyAccountExporter(AccountReportExporter):
    def __init__(self, settings: Settings, start: date) -> None:
        super().__init__(settings)
        self.start = start

    def _pdf_filename(self, party: str) -> str:
        return statement_filename(party + " - Copy account")

    def _verify_export_pdf(self, path: Path, party: str, as_of: date) -> Any:
        return verify_account_pdf(path, party, as_of, self.start)

    def export_ledger(self, party: str, end: date, directory: Path) -> Path:
        main, desktop = self._main()
        target, fields = self._open_ledger(main, desktop)
        values = [
            "STANDARD",
            party,
            self.start.strftime("%d-%m-%Y"),
            end.strftime("%d-%m-%Y"),
            "Single Account (Auto)",
            "Name",
            *(["N"] * 8),
            "Y",
        ]
        for field, value in zip(fields, values, strict=True):
            self._set(field, value)
        if [field.get_value().strip().casefold() for field in fields] != [
            value.casefold() for value in values
        ]:
            raise SyncError("BUSY did not retain the Copy account settings.")
        self._click(target, r"OK\s*\(F2\)")
        target = self._wait(
            main, desktop, self._is_report, self.settings.pouncha_export_timeout_seconds
        )
        return self._export_pdf(main, desktop, target, directory, party, end)


class GroupBalancesExporter(AccountReportExporter):
    def _pdf_filename(self, party: str) -> str:
        return statement_filename(party + " - Closing balances")

    def _verify_export_pdf(self, path: Path, party: str, as_of: date) -> Any:
        return verify_account_pdf(path, party, as_of)

    def _options(self, target: Any, group: str, as_of: date) -> None:
        fields = self._edits(target)
        if len(fields) != 7:
            raise SyncError("BUSY's group closing-balance options changed. No fields were guessed.")
        values = [group, as_of.strftime("%d-%m-%Y"), "Name", "N", "N", "Not Required", "N"]
        for field, value in zip(fields, values, strict=True):
            self._set(field, value)
        if [field.get_value().strip().casefold() for field in fields] != [
            value.casefold() for value in values
        ]:
            raise SyncError("BUSY did not retain the group closing-balance settings.")

    def export_group(self, group: str, as_of: date, directory: Path) -> tuple[Path, dict[str, Any]]:
        main, desktop = self._main()
        fy, _, _ = financial_year(india_today())
        title_year = re.search(r"F\.Y\.\s*(\d{4})-(\d{2})", main.window_text(), re.I)
        if title_year is None or f"{int(title_year[1]) % 100:02d}-{title_year[2]}" != fy:
            raise SyncError(
                f"Open BUSY in the current financial year {fy} for group closing balances."
            )
        if not self._home(main, desktop):
            raise SyncError("BUSY did not reach its homepage safely.")
        self._guard(main, desktop)[0].type_keys("%f", pause=0.2)
        self._guard(main, desktop)[0].type_keys("account{SPACE}g{ENTER}", pause=0.05)
        target = self._wait(
            main, desktop, lambda root: bool(self._buttons(root, "Group of Accounts"))
        )
        self._click(target, "Group of Accounts")
        target = self._wait(main, desktop, lambda root: len(self._edits(root)) == 7)
        self._options(target, group, as_of)
        self._click(target, r"OK\s*\(F2\)")
        target = self._wait(
            main, desktop, self._is_report, self.settings.pouncha_export_timeout_seconds
        )
        with TemporaryDirectory(prefix="account-group-") as temp:
            excel = Path(temp) / "balances.xlsx"
            self._excel(main, desktop, target, excel)
            snapshot = parse_group_balances(excel, group, as_of)
        path = directory / self._pdf_filename(group)
        render_group_pdf(snapshot, path)
        self._verify_export_pdf(path, group, as_of)
        return path, snapshot
