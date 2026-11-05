"""Convert exported Sales ledger blocks without mistaking transport for a challan."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from openpyxl import load_workbook  # type: ignore[import-untyped]


class SyncError(RuntimeError):
    """An actionable, safe-to-display sync failure."""


def text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def bill_key(value: str) -> str:
    result = re.sub(r"\s+", "", value).upper()
    match = re.fullmatch(r"(HST(?:/L)?)/(\d{2}-\d{2})/(\d+)", result)
    if not match:
        raise SyncError(f"Unrecognized bill number: {value[:80]}")
    return f"{match[1]}/{match[2]}/{int(match[3])}"


def parse_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text(value), fmt).date()
        except ValueError:
            pass
    raise SyncError(f"Invalid voucher date: {text(value)[:40]}")


@dataclass(frozen=True)
class Sale:
    date: date
    bill: str
    party: str
    transport: str = ""
    vehicle: str = ""
    station: str = ""
    challan: str = ""

    def cells(self) -> list[str]:
        return [
            self.date.strftime("%d/%m/%Y"),
            self.bill,
            self.party,
            self.transport,
            self.vehicle,
            self.station,
            self.challan,
        ]


def sort_key(sale: Sale) -> tuple[date, int, int]:
    key = bill_key(sale.bill)
    return sale.date, int(key.startswith("HST/L/")), int(key.rsplit("/", 1)[1])


def parse_sales(path: Path, company: str, start: date, end: date) -> list[Sale]:
    if path.stat().st_size > 25 * 1024 * 1024:
        raise SyncError("The export exceeds the 25 MiB limit.")
    try:
        with ZipFile(path) as archive:
            if sum(item.file_size for item in archive.infolist()) > 100 * 1024 * 1024:
                raise SyncError("The workbook expands beyond the safe size limit.")
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            sheet = workbook.worksheets[0]
            if sheet.max_row and sheet.max_row > 100_000:
                raise SyncError("Export has too many rows; select a shorter date range.")
            rows = list(sheet.iter_rows(max_col=12, values_only=True))
        finally:
            workbook.close()
    except SyncError:
        raise
    except Exception as exc:
        raise SyncError("Cannot read the export. Supply an unlocked .xlsx Sales ledger.") from exc
    header = next(
        (
            i
            for i, row in enumerate(rows[:40])
            if [text(v) for v in row[:4]] == ["Date", "Type", "Vch/Bill No", "Account"]
        ),
        None,
    )
    if header is None:
        raise SyncError("Sales ledger column headings were not found.")
    preamble = " ".join(text(v) for row in rows[:header] for v in row)

    def normalize(value: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", value.upper())

    if not any(
        normalize(text(value)) == normalize(company)
        for row in rows[:header]
        for value in row
        if value is not None
    ):
        raise SyncError("The export belongs to a different company.")
    if not re.search(r"Account\s*:\s*Sales\b(?!\s+Return)", preamble, re.I):
        raise SyncError("Export the Sales account ledger, not another account.")
    result: dict[str, Sale] = {}
    current: dict[str, Any] | None = None

    def finish() -> None:
        if current is None:
            return
        sale = Sale(**current)
        key = bill_key(sale.bill)
        if key in result and result[key] != sale:
            raise SyncError(f"Conflicting duplicate bill in export: {sale.bill}")
        result[key] = sale

    for row in rows[header + 1 :]:
        if text(row[1]).casefold() == "sale":
            finish()
            day = parse_date(row[0])
            if not start <= day <= end:
                raise SyncError("Export contains a bill outside the selected dates.")
            if not text(row[3]):
                raise SyncError("A Sale row is missing its party name.")
            current = dict(
                date=day,
                bill=text(row[2]),
                party=text(row[3]),
                transport="",
                vehicle="",
                station="",
                challan="",
            )
            continue
        if row[0] is not None or text(row[1]) or text(row[3]).casefold() == "total":
            finish()
            current = None
        if current is None:
            continue
        detail = text(row[3])
        match = re.match(r"^(Transport|Vehicle\s+No\.?|Station)\s*:\s*(.*)$", detail, re.I)
        if match:
            field = "vehicle" if match[1].lower().startswith("vehicle") else match[1].lower()
            value = match[2].strip()
        else:
            reference = re.fullmatch(
                r"(?:(?:ORDER|CHALLAN)\s+NO\.?\s*:?\s*)?((?:HSL|HS)\s*[-/]\s*\d+)",
                detail,
                re.I,
            )
            if not reference:
                continue
            field, value = "challan", reference[1].strip()
        if current[field] and current[field] != value:
            raise SyncError(f"Conflicting {field} for {current['bill']}; check the export.")
        current[field] = value
    finish()
    return sorted(result.values(), key=sort_key)
