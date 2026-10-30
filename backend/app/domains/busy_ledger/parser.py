"""Adaptive, ephemeral parsing of BUSY register Excel exports.

Only the exported workbook is read. The source file is removed after parsing,
whether parsing succeeds or fails, and no BUSY database or installation file is
ever opened.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from openpyxl import load_workbook  # type: ignore[import-untyped]

from app.domains.busy_ledger.normalizer import (
    DEFAULT_SERIES_ALIASES,
    canonicalize_series,
    normalize_party_tokens,
    parse_busy_voucher,
)

try:  # Legacy .xls support is optional at import time but declared as a dependency.
    import xlrd  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - exercised only on an incomplete install
    xlrd = None

SUPPORTED_WORKBOOK_SUFFIXES = frozenset({".xlsx", ".xlsm", ".xls"})
CATEGORY_VALUES = frozenset({"bills", "credit_notes", "debit_notes"})
HEADER_SCAN_ROWS = 25
DELETE_ATTEMPTS = 3
DELETE_BACKOFF_SECONDS = 0.2
MAX_WARNINGS = 40

HEADER_SYNONYMS: dict[str, tuple[str, ...]] = {
    "date": (
        "date",
        "vch date",
        "voucher date",
        "bill date",
        "inv date",
        "invoice date",
    ),
    "voucher_no": (
        "vch no",
        "voucher no",
        "vch bill no",
        "bill no",
        "invoice no",
        "inv no",
        "doc no",
        "document no",
        "cn no",
        "dn no",
    ),
    "voucher_type": ("vch type", "voucher type", "type"),
    "party": (
        "party",
        "party name",
        "account",
        "account name",
        "particulars",
        "customer",
        "customer name",
    ),
}
TOTAL_ROW_RE = re.compile(r"\b(grand\s+total|sub\s*total|total)\b", re.IGNORECASE)
_TOTAL_LABELS = frozenset({"total", "grand total", "sub total", "subtotal", "grandtotal"})


class BusyLedgerError(ValueError):
    """Raised when a workbook cannot be recognized safely."""


@dataclass(frozen=True, slots=True)
class ParsedLedgerRow:
    category: str
    raw_voucher_no: str
    canonical_series: str
    fy: str
    serial: int
    voucher_date: date
    party_name: str
    normalized_party: str


@dataclass(frozen=True, slots=True)
class ParsedWorkbook:
    source_file: Path
    category_hint: str | None
    detected_headers: dict[str, str]
    rows_found: int
    rows: tuple[ParsedLedgerRow, ...]
    warnings: tuple[str, ...]
    min_date: date | None
    max_date: date | None
    deleted: bool


@dataclass(frozen=True, slots=True)
class _HeaderMapping:
    row_index: int
    columns: dict[str, int]
    display: dict[str, str]


def normalize_header_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


_NORMALIZED_SYNONYMS: dict[str, frozenset[str]] = {
    field: frozenset(normalize_header_text(synonym) for synonym in synonyms)
    for field, synonyms in HEADER_SYNONYMS.items()
}


def parse_voucher_date(value: Any) -> date | None:
    """Parse native dates, Excel serial numbers and common BUSY string dates."""

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if value <= 0:
            return None
        # Excel's 1900 date system, including its deliberate off-by-one quirk.
        return date(1899, 12, 30) + timedelta(days=int(value))

    text = str(value or "").strip()
    if not text:
        return None
    if ":" in text and " " in text:
        text = text.split(" ", 1)[0].strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}(?:[T ].*)?$", text):
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            pass
    for date_format in (
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%d.%m.%Y",
        "%d-%m-%y",
        "%d/%m/%y",
        "%d.%m.%y",
        "%d-%b-%Y",
        "%d-%b-%y",
        "%d %b %Y",
        "%d %b %y",
        "%d-%B-%Y",
        "%d-%B-%y",
        "%d %B %Y",
        "%d %B %y",
    ):
        try:
            return datetime.strptime(text, date_format).date()
        except ValueError:
            continue
    return None


def infer_category(
    *, category_hint: str | None, voucher_type: str, party: str, preamble: str, series: str
) -> str:
    if category_hint in CATEGORY_VALUES:
        return category_hint
    normalized_type = " ".join(voucher_type.split()).casefold()
    if normalized_type in {"salereturn", "slrt"}:
        return "credit_notes"
    if normalized_type in {"purchase return", "prrt", "purcreturn"}:
        return "debit_notes"
    combined = " ".join((voucher_type, party, preamble)).casefold()
    if "credit note" in combined or re.search(r"\bcredit\s+notes?\b", combined):
        return "credit_notes"
    if "debit note" in combined or re.search(r"\bdebit\s+notes?\b", combined):
        return "debit_notes"
    compact = re.sub(r"[^A-Z0-9]", "", series.upper())
    if compact.startswith("CN"):
        return "credit_notes"
    if compact.startswith("DN"):
        return "debit_notes"
    if re.search(r"\bsales?\b|\bbills?\b|\binvoices?\b", combined):
        return "bills"
    return "bills"


def delete_with_retries(
    path: Path,
    *,
    attempts: int = DELETE_ATTEMPTS,
    backoff_seconds: float = DELETE_BACKOFF_SECONDS,
) -> bool:
    """Permanently remove an ephemeral workbook, tolerating a brief Windows lock."""

    for attempt in range(attempts):
        try:
            path.unlink(missing_ok=True)
            return True
        except OSError:
            if attempt == attempts - 1:
                return False
            time.sleep(backoff_seconds)
    return False


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _row_texts(row: Sequence[Any]) -> list[str]:
    return [text for value in row if (text := _cell_text(value))]


def _detect_header(rows: Sequence[Sequence[Any]]) -> _HeaderMapping | None:
    limit = min(len(rows), HEADER_SCAN_ROWS)
    for row_index in range(limit):
        columns: dict[str, int] = {}
        display: dict[str, str] = {}
        for column_index, value in enumerate(rows[row_index]):
            normalized = normalize_header_text(value)
            if not normalized:
                continue
            for field, synonyms in _NORMALIZED_SYNONYMS.items():
                if field in columns:
                    continue
                if normalized in synonyms:
                    columns[field] = column_index
                    display[field] = _cell_text(value)
                    break
        if "date" in columns and "voucher_no" in columns:
            return _HeaderMapping(row_index=row_index, columns=columns, display=display)
    return None


def _cell(row: Sequence[Any], columns: Mapping[str, int], field: str) -> Any:
    index = columns.get(field)
    if index is None or index >= len(row):
        return None
    return row[index]


def _is_total_label(text: str) -> bool:
    compact = " ".join(text.casefold().split())
    return compact in _TOTAL_LABELS


def _read_xlsx_sheets(path: Path) -> list[list[list[Any]]]:
    workbook = load_workbook(filename=path, read_only=True, data_only=True)
    try:
        return [
            [list(row) for row in worksheet.iter_rows(values_only=True)]
            for worksheet in workbook.worksheets
        ]
    finally:
        workbook.close()


def _read_xls_sheets(path: Path) -> list[list[list[Any]]]:
    if xlrd is None:
        raise BusyLedgerError(
            "Reading legacy .xls exports requires xlrd. Export the register as .xlsx instead."
        )
    workbook = xlrd.open_workbook(str(path), on_demand=True)
    try:
        sheets: list[list[list[Any]]] = []
        for sheet in workbook.sheets():
            rows: list[list[Any]] = []
            for row_index in range(sheet.nrows):
                values: list[Any] = []
                for column_index in range(sheet.ncols):
                    cell = sheet.cell(row_index, column_index)
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        values.append(xlrd.xldate_as_datetime(cell.value, workbook.datemode))
                    else:
                        values.append(cell.value)
                rows.append(values)
            sheets.append(rows)
        return sheets
    finally:
        workbook.release_resources()


def _read_sheets(path: Path) -> list[list[list[Any]]]:
    suffix = path.suffix.casefold()
    if suffix in {".xlsx", ".xlsm"}:
        return _read_xlsx_sheets(path)
    if suffix == ".xls":
        return _read_xls_sheets(path)
    raise BusyLedgerError(f"Unsupported workbook type: {path.suffix or 'unknown'}")


def _append_warning(warnings: list[str], message: str) -> None:
    if len(warnings) < MAX_WARNINGS:
        warnings.append(message)


def _parse_sheet(
    rows: Sequence[Sequence[Any]],
    *,
    category_hint: str | None,
    aliases: Mapping[str, str],
    sheet_name: str,
    seen: set[tuple[str, str, date]],
    parsed: list[ParsedLedgerRow],
    warnings: list[str],
) -> bool:
    mapping = _detect_header(rows)
    if mapping is None:
        return False

    preamble = " ".join(
        text for row in rows[: mapping.row_index] for text in _row_texts(row)
    )
    previous_voucher = ""
    for row_index in range(mapping.row_index + 1, len(rows)):
        row = rows[row_index]
        if not _row_texts(row):
            continue

        date_value = _cell(row, mapping.columns, "date")
        voucher_text = _cell_text(_cell(row, mapping.columns, "voucher_no"))
        voucher_type = _cell_text(_cell(row, mapping.columns, "voucher_type"))
        party_name = _cell_text(_cell(row, mapping.columns, "party"))
        voucher_date = parse_voucher_date(date_value)

        if _is_total_label(voucher_text):
            continue
        if voucher_date is None:
            joined = " ".join(_row_texts(row))
            if TOTAL_ROW_RE.search(joined):
                continue
            # Detailed registers repeat item lines with a blank date and/or
            # voucher. They are not separate vouchers.
            if not voucher_text or voucher_text == previous_voucher:
                continue
            _append_warning(
                warnings, f"{sheet_name} row {row_index + 1}: unrecognized date ignored"
            )
            continue
        if not voucher_text:
            continue

        voucher_key = parse_busy_voucher(voucher_text)
        if voucher_key is None:
            joined = " ".join(_row_texts(row))
            if TOTAL_ROW_RE.search(joined):
                continue
            _append_warning(
                warnings,
                f"{sheet_name} row {row_index + 1}: voucher number "
                f"{voucher_text!r} has no serial number",
            )
            continue

        category = infer_category(
            category_hint=category_hint,
            voucher_type=voucher_type,
            party=party_name,
            preamble=preamble,
            series=voucher_key.compact_series,
        )
        canonical = canonicalize_series(voucher_key.compact_series, aliases)
        dedupe_key = (category, voucher_text, voucher_date)
        previous_voucher = voucher_text
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        parsed.append(
            ParsedLedgerRow(
                category=category,
                raw_voucher_no=voucher_text,
                canonical_series=canonical,
                fy=voucher_key.fy or "",
                serial=voucher_key.serial,
                voucher_date=voucher_date,
                party_name=party_name,
                normalized_party=" ".join(sorted(normalize_party_tokens(party_name))),
            )
        )
    return True


def parse_busy_workbook(
    path: Path,
    *,
    category_hint: str | None = None,
    aliases: Mapping[str, str] | None = None,
    delete_source: bool = True,
) -> ParsedWorkbook:
    """Parse and permanently delete one BUSY register export.

    Deletion runs in ``finally`` so a malformed workbook cannot be left behind.
    """

    source = Path(path)
    if source.suffix.casefold() not in SUPPORTED_WORKBOOK_SUFFIXES:
        raise BusyLedgerError(f"Unsupported workbook type: {source.suffix or 'unknown'}")
    if not source.is_file():
        raise BusyLedgerError(f"Workbook not found: {source.name}")

    resolved_aliases = dict(DEFAULT_SERIES_ALIASES)
    if aliases:
        resolved_aliases.update({key.upper(): value.upper() for key, value in aliases.items()})

    parsed: list[ParsedLedgerRow] = []
    warnings: list[str] = []
    seen: set[tuple[str, str, date]] = set()
    detected_headers: dict[str, str] = {}
    deleted = False
    try:
        if category_hint is not None and category_hint not in CATEGORY_VALUES:
            raise BusyLedgerError(f"Unknown document category: {category_hint}")
        sheets = _read_sheets(source)
        found_header = False
        for sheet_index, rows in enumerate(sheets):
            sheet_name = f"Sheet {sheet_index + 1}"
            mapping = _detect_header(rows)
            if mapping is not None and not detected_headers:
                detected_headers = dict(mapping.display)
            if _parse_sheet(
                rows,
                category_hint=category_hint,
                aliases=resolved_aliases,
                sheet_name=sheet_name,
                seen=seen,
                parsed=parsed,
                warnings=warnings,
            ):
                found_header = True
        if not found_header:
            raise BusyLedgerError(
                "No BUSY ledger header row was found in the first "
                f"{HEADER_SCAN_ROWS} rows (expected date and voucher-number columns)."
            )
    except BusyLedgerError:
        raise
    except Exception as exc:
        raise BusyLedgerError(
            f"Could not read the workbook: {type(exc).__name__}"
        ) from exc
    finally:
        if delete_source:
            deleted = delete_with_retries(source)
            if not deleted:
                _append_warning(
                    warnings,
                    f"Could not delete the ephemeral workbook after {DELETE_ATTEMPTS} attempts.",
                )

    dates = [row.voucher_date for row in parsed]
    return ParsedWorkbook(
        source_file=source,
        category_hint=category_hint,
        detected_headers=detected_headers,
        rows_found=len(parsed),
        rows=tuple(parsed),
        warnings=tuple(warnings),
        min_date=min(dates) if dates else None,
        max_date=max(dates) if dates else None,
        deleted=deleted,
    )


def workbook_paths(directory: Path) -> list[Path]:
    """Return pending workbook files in a stable order, excluding Office locks."""

    if not directory.is_dir():
        return []
    return sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file()
            and path.suffix.casefold() in SUPPORTED_WORKBOOK_SUFFIXES
            and not path.name.startswith("~$")
        ),
        key=lambda path: path.name.casefold(),
    )


def summarize_headers(headers: Mapping[str, str]) -> Iterable[tuple[str, str]]:
    return sorted(headers.items())
