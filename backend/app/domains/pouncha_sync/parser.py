"""Parse the BUSY Account Ledger Sales export for Pouncha sync.

The BUSY export has a report preamble, one header row, and detail sub-rows under
each Sale voucher. The parser locates the header dynamically, extracts only
``Type == "Sale"`` vouchers, and stops at the next voucher or total row so a
short bill cannot read the next bill's transport lines.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook  # type: ignore[import-untyped]
from openpyxl.utils import get_column_letter  # type: ignore[import-untyped]
from openpyxl.utils.datetime import from_excel  # type: ignore[import-untyped]

from app.domains.busy_ledger.normalizer import (
    DEFAULT_SERIES_ALIASES,
    canonicalize_series,
    parse_busy_voucher,
)
from app.domains.pouncha_sync.models import (
    ParsedPounchaWorkbook,
    PounchaSaleRecord,
)

HEADER_SCAN_ROWS = 15
MAX_SUBROWS = 10
OUTPUT_HEADERS = (
    "Date",
    "Vch/Bill No",
    "Account",
    "Transport",
    "Vehicle No.",
    "Station",
    "Order No.",
)

_HEADER_ALIASES: dict[str, frozenset[str]] = {
    "date": frozenset({"date", "vchdate", "voucherdate", "billdate"}),
    "type": frozenset({"type", "vchtype", "vouchertype"}),
    "voucher_no": frozenset(
        {"vch/billno", "vchbillno", "vchno", "billno", "voucherno"}
    ),
    "account": frozenset({"account", "accountname", "party", "partyname"}),
}
_FIELD_LABELS = {
    "transport": "TRANSPORT",
    "vehicle_no": "VEHICLE NO",
    "station": "STATION",
}
_ORDER_REJECT_LABELS = (
    "TRANSPORT",
    "VEHICLE NO",
    "STATION",
    "E-WAY BILL",
    "EWAY BILL",
    "TOTAL",
    "CLOSING BAL",
)
_ORDER_REJECT_NORMALIZED = frozenset(
    re.sub(r"[^A-Z0-9]+", " ", label.upper()).strip()
    for label in _ORDER_REJECT_LABELS
)
_DETAIL_LABELS = frozenset(
    {"TRANSPORT", "VEHICLE NO", "STATION", "E WAY BILL", "EWAY BILL", "ORDER NO"}
)
_TOTAL_LABELS = frozenset({"TOTAL", "CLOSING BAL", "CLOSINGBAL", "CLOSING BALANCE"})
_DATE_FORMATS = (
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d.%m.%Y",
    "%d-%b-%Y",
    "%d-%b-%y",
    "%d %b %Y",
    "%d %b %y",
    "%Y-%m-%d",
    "%Y/%m/%d",
)


class PounchaParseError(ValueError):
    """Raised when the workbook does not look like a BUSY Account Ledger export."""


def parse_pouncha_sales_workbook(path: Path) -> ParsedPounchaWorkbook:
    """Read one BUSY Account Ledger Sales workbook and return Sale records."""

    source = Path(path)
    if source.suffix.casefold() not in {".xlsx", ".xlsm"}:
        raise PounchaParseError(
            f"Unsupported Pouncha workbook type: {source.suffix or 'unknown'}. "
            "Export the BUSY Account Ledger as Microsoft Excel (.xlsx)."
        )
    if not source.is_file():
        raise PounchaParseError(f"Pouncha workbook not found: {source.name}")

    workbook = None
    try:
        workbook = load_workbook(source, read_only=True, data_only=True)
    except Exception as exc:
        raise PounchaParseError(
            f"Could not read {source.name} as an Excel workbook: {exc}"
        ) from exc
    try:
        for worksheet in workbook.worksheets:
            rows = [tuple(row) for row in worksheet.iter_rows(values_only=True)]
            header = _detect_header(rows)
            if header is None:
                continue
            row_index, mapping = header
            records, warnings = _parse_rows(
                rows,
                row_index=row_index,
                mapping=mapping,
                sheet_name=worksheet.title,
            )
            return ParsedPounchaWorkbook(
                records=tuple(records),
                warnings=tuple(warnings),
                sheet_name=worksheet.title,
            )
    finally:
        workbook.close()

    raise PounchaParseError(
        "Could not find the Account Ledger header row. Expected columns "
        "'Date', 'Type', 'Vch/Bill No' and 'Account' in the first "
        f"{HEADER_SCAN_ROWS} rows of the exported workbook."
    )


def _detect_header(
    rows: Sequence[Sequence[Any]],
) -> tuple[int, dict[str, int]] | None:
    for row_index, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        mapping: dict[str, int] = {}
        for column_index, value in enumerate(row):
            normalized = _normalize_header(value)
            if not normalized:
                continue
            for role, aliases in _HEADER_ALIASES.items():
                if role not in mapping and normalized in aliases:
                    mapping[role] = column_index
                    break
        if len(mapping) == len(_HEADER_ALIASES):
            return row_index, mapping
    return None


def _parse_rows(
    rows: Sequence[Sequence[Any]],
    *,
    row_index: int,
    mapping: dict[str, int],
    sheet_name: str,
) -> tuple[list[PounchaSaleRecord], list[str]]:
    records: list[PounchaSaleRecord] = []
    warnings: list[str] = []
    seen: set[str] = set()
    index = row_index + 1
    while index < len(rows):
        row = rows[index]
        voucher_type = _cell_text(_cell(row, mapping["type"]))
        if voucher_type.casefold() != "sale":
            index += 1
            continue

        voucher_no = _cell_text(_cell(row, mapping["voucher_no"]))
        account = _cell_text(_cell(row, mapping["account"]))
        parsed_date = _parse_date(_cell(row, mapping["date"]))
        if not voucher_no:
            warnings.append(
                f"{sheet_name} row {index + 1}: Sale row without a voucher number skipped."
            )
            index += 1
            continue
        if parsed_date is None:
            warnings.append(
                f"{sheet_name} row {index + 1}: Sale voucher {voucher_no!r} has an "
                "unrecognized date and was skipped."
            )
            index += 1
            continue

        details = _extract_details(rows, index, mapping)
        record = PounchaSaleRecord(
            date=parsed_date,
            voucher_no=voucher_no,
            account=account,
            transport=details["transport"],
            vehicle_no=details["vehicle_no"],
            station=details["station"],
            order_no=details["order_no"],
        )

        identity = voucher_identity(voucher_no)
        if identity in seen:
            warnings.append(
                f"{sheet_name} row {index + 1}: duplicate Sale voucher "
                f"{voucher_no!r} skipped."
            )
        else:
            seen.add(identity)
            records.append(record)
        index += 1

    return records, warnings


def _extract_details(
    rows: Sequence[Sequence[Any]],
    sale_index: int,
    mapping: dict[str, int],
) -> dict[str, str]:
    details = {
        "transport": "",
        "vehicle_no": "",
        "station": "",
        "order_no": "",
    }
    stop = min(sale_index + 1 + MAX_SUBROWS, len(rows))
    for index in range(sale_index + 1, stop):
        row = rows[index]
        if _is_boundary_row(row, mapping):
            break
        texts = [_cell_text(value) for value in row]
        if not any(texts):
            continue

        if index == sale_index + 1:
            details["order_no"] = _extract_order_no(
                _cell_text(_cell(row, mapping["account"]))
            )

        for field, label in _FIELD_LABELS.items():
            if details[field]:
                continue
            value = _extract_label_value(texts, label)
            if value:
                details[field] = value.upper() if field == "station" else value
    return details


def _is_boundary_row(
    row: Sequence[Any], mapping: dict[str, int]
) -> bool:
    if _has_text(_cell(row, mapping["voucher_no"])):
        return True
    if _has_text(_cell(row, mapping["type"])):
        return True
    account = _normalize_label(_cell(row, mapping["account"]))
    if account in _TOTAL_LABELS:
        return True
    if not _has_text(_cell(row, mapping["date"])):
        return False
    if not account:
        return True
    return not any(label in account for label in _DETAIL_LABELS)


def _extract_order_no(text: str) -> str:
    value = text.strip()
    if not value:
        return ""
    normalized = _normalize_label(value)
    if not normalized:
        return ""
    if any(label in normalized for label in _ORDER_REJECT_NORMALIZED):
        return ""
    value = re.sub(r"(?i)^\s*ORDER\s*NO\.?\s*:?\s*", "", value)
    value = _strip_busy_zero_suffix(value)
    return value.strip(" :\t\r\n")


def _extract_label_value(texts: Sequence[str], label: str) -> str:
    for index, text in enumerate(texts):
        normalized = _normalize_label(text)
        if not normalized.startswith(label):
            continue
        if ":" in text:
            value = _value_after_colon(text)
            if value:
                return value
        for following in texts[index + 1 :]:
            candidate = _strip_busy_zero_suffix(following).strip(" :\t\r\n")
            if candidate:
                return candidate
    return ""


def _value_after_colon(text: str) -> str:
    value = text.split(":", 1)[1] if ":" in text else text
    return _strip_busy_zero_suffix(value).strip(" :\t\r\n")


def _strip_busy_zero_suffix(value: str) -> str:
    return re.sub(r"\s+0(?:\s+0){2,}.*$", "", value)


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            converted = from_excel(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if isinstance(converted, datetime):
            return converted.date()
        if isinstance(converted, date):
            return converted
        return None
    text = str(value or "").strip()
    if not text:
        return None
    for date_format in _DATE_FORMATS:
        try:
            return datetime.strptime(text, date_format).date()
        except ValueError:
            continue
    return None


def _cell(row: Sequence[Any], index: int) -> Any:
    return row[index] if index < len(row) else None


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d-%m-%Y")
    if isinstance(value, date):
        return value.strftime("%d-%m-%Y")
    return str(value).strip()


def _has_text(value: Any) -> bool:
    return _cell_text(value) != ""


def _normalize_header(value: Any) -> str:
    return re.sub(r"[\s.]+", "", _cell_text(value).casefold())


def _normalize_label(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", _cell_text(value).upper()).strip()


def voucher_identity(voucher_no: str) -> str:
    """Return the canonical deduplication key for a BUSY voucher number."""

    parsed = parse_busy_voucher(voucher_no)
    if parsed is None:
        return re.sub(r"[^A-Z0-9]+", "", voucher_no.upper())
    series = canonicalize_series(parsed.compact_series, DEFAULT_SERIES_ALIASES)
    return f"{series}|{parsed.fy or ''}|{parsed.serial}"


def voucher_sort_key(record: PounchaSaleRecord) -> tuple[date, int, int, str]:
    """Sort by date, then HST before HST/L, then serial number."""

    parsed = parse_busy_voucher(record.voucher_no)
    if parsed is None:
        return (record.date, 1, 0, record.voucher_no.upper())
    compact = parsed.compact_series.upper()
    is_branch = "/L/" in record.voucher_no.upper() or compact in {
        "HSTL",
        "HSL",
    }
    return (
        record.date,
        1 if is_branch else 0,
        parsed.serial,
        record.voucher_no.upper(),
    )


def write_pouncha_archive(
    records: Sequence[PounchaSaleRecord], target: Path
) -> Path:
    """Append new sale rows to the local archival workbook.

    Existing rows, existing voucher numbers and any extra columns (for example
    Column H remarks) are preserved. A fresh workbook gets the A:G header; an
    existing workbook keeps its own header or headerless layout.
    """

    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing_keys = _read_archive_keys(path)
    known = set(existing_keys)
    fresh: list[PounchaSaleRecord] = []
    for record in records:
        key = voucher_identity(record.voucher_no)
        if key in known:
            continue
        known.add(key)
        fresh.append(record)
    fresh.sort(key=voucher_sort_key)

    if path.is_file():
        workbook = load_workbook(path)
        worksheet = workbook.active
        new_workbook = False
        if _sheet_is_empty(worksheet):
            worksheet.append(list(OUTPUT_HEADERS))
            new_workbook = True
    else:
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Pouncha Sales"
        worksheet.append(list(OUTPUT_HEADERS))
        new_workbook = True

    if not fresh:
        workbook.close()
        return path

    for record in fresh:
        worksheet.append(record.as_sheet_row())
    if new_workbook:
        _set_archive_widths(worksheet, fresh)

    temporary = path.with_name(path.name + ".tmp")
    workbook.save(temporary)
    workbook.close()
    temporary.replace(path)
    return path


def _read_archive_keys(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        worksheet = workbook.active
        rows = worksheet.iter_rows(values_only=True)
        first = next(rows, None)
        if first is None:
            return set()
        start = 1 if _looks_like_archive_header(first) else 0
        keys: set[str] = set()
        for row in list(rows) if start == 1 else [first, *rows]:
            value = row[1] if len(row) > 1 else None
            if value is None or not str(value).strip():
                continue
            keys.add(voucher_identity(str(value)))
        return keys
    finally:
        workbook.close()


def _looks_like_archive_header(row: Sequence[Any]) -> bool:
    normalized = {
        re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()
        for value in row
        if value is not None
    }
    has_date = "date" in normalized
    has_voucher = bool(
        normalized
        & {"vch bill no", "vch no", "bill no", "voucher no"}
    )
    return has_date and has_voucher


def _sheet_is_empty(worksheet: Any) -> bool:
    if worksheet.max_row > 1:
        return False
    return all(cell.value is None for cell in worksheet[1])


def _set_archive_widths(
    worksheet: Any, records: Sequence[PounchaSaleRecord]
) -> None:
    for column_index, header in enumerate(OUTPUT_HEADERS, start=1):
        lengths = [len(header)]
        for record in records:
            lengths.append(len(record.as_sheet_row()[column_index - 1]))
        worksheet.column_dimensions[get_column_letter(column_index)].width = min(
            max(lengths) + 2, 50
        )
