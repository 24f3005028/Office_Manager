"""Exact invoice identity from PDF headers; no BUSY database access."""

from __future__ import annotations

import hashlib
import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pymupdf

from app.domains.documents.scanner import DocumentScanner
from app.domains.mobile.reports import statement_filename

VOUCHER = r"([A-Z]+(?:/[A-Z]+)?)/(?:20)?(\d{2})-(?:20)?(\d{2})/(\d+)"
LEGACY = r"([A-Z]+(?:/[A-Z]+)?)/(\d+)/(?:20)?(\d{2})-(?:20)?(\d{2})"
HEADER = re.compile(
    r"(?:Invoice|Bill|Voucher)\s*(?:No\.?|Number)\s*:?\s*((?:" + VOUCHER + "|" + LEGACY + r"))\b",
    re.I,
)
FULL = re.compile(VOUCHER, re.I)


def invoice_filename(row: dict[str, Any]) -> str:
    party = str(row.get("party_name") or "").strip()
    if not party or party == "See PDF for party name":
        raise ValueError("The party name could not be read. Ask the office to check this bill PDF.")
    return statement_filename(str(row["bill_number"]) + " - " + party)


def parse_number(value: str) -> tuple[str, str, int] | None:
    parsed = FULL.fullmatch(value)
    if parsed:
        series, first, last, serial = parsed.groups()
    else:
        parsed = re.fullmatch(LEGACY, value, re.I)
        if parsed is None:
            return None
        series, serial, first, last = parsed.groups()
    if (int(last) - int(first)) % 100 != 1:
        return None
    return series.upper(), f"{first}-{last}", int(serial)


def identity(text: str) -> dict[str, Any] | None:
    matches = list(HEADER.finditer(text))
    numbers = {re.sub(r"\s+", "", match[1]).upper() for match in matches}
    if len(numbers) != 1:
        return None
    number = numbers.pop()
    parsed = parse_number(number)
    if parsed is None:
        return None
    party = re.search(r"Billed\s+to\s*:?\s*(?:Shipped\s+to\s*:?\s*)?([^\r\n]+)", text, re.I)
    dated = re.search(r"\bDated\s*:?\s*(\d{1,2}-\d{1,2}-\d{4})", text, re.I)
    return {
        "bill_number": number,
        "financial_year": parsed[1],
        "serial": parsed[2],
        "series": parsed[0],
        "party_name": party[1].strip() if party else "See PDF for party name",
        "date": dated[1] if dated else "",
    }


class InvoiceCatalogue:
    def __init__(
        self, scanner: DocumentScanner, roots_provider: Callable[[], list[Path]] | None = None
    ) -> None:
        self.scanner = scanner
        self.roots_provider = roots_provider
        self._cache: dict[str, tuple[int, int, dict[str, Any] | None]] = {}
        self._lock = threading.Lock()

    def entries(
        self,
        serial_filter: int | None = None,
        sample_years: bool = False,
        file_id_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        entries = []
        sampled_roots: set[int] = set()
        with self._lock:
            if self.roots_provider:
                self.scanner.set_roots({"bills": self.roots_provider()})
            for record in self.scanner.scan(categories=["bills"]):
                if file_id_filter is not None and record.file_id != file_id_filter:
                    continue
                if sample_years and record.root_index in sampled_roots:
                    continue
                # Filenames only narrow candidates; PDF headers remain authoritative.
                # This avoids parsing every archived PDF for a single bill lookup.
                hint = re.match(
                    r"^(?:[A-Za-z/]+[-_ ]+)?"
                    r"(?:(?:20)?\d{2}[-_]\d{2}[-_ ])?(\d+)(?:\D|$)",
                    record.path.stem,
                )
                if serial_filter is not None and hint and int(hint[1]) != serial_filter:
                    continue
                try:
                    stat = record.path.stat()
                    cached = self._cache.get(record.file_id)
                    if cached is None or cached[:2] != (stat.st_mtime_ns, stat.st_size):
                        parsed = None
                        if 0 < stat.st_size <= 25 * 1024 * 1024:
                            with pymupdf.open(record.path) as pdf:  # type: ignore[no-untyped-call]
                                if pdf.page_count and not pdf.is_encrypted:
                                    parsed = identity(str(pdf[0].get_text()))
                        self._cache[record.file_id] = (stat.st_mtime_ns, stat.st_size, parsed)
                    parsed = self._cache[record.file_id][2]
                    if parsed:
                        root = self.scanner.roots_by_category["bills"][record.root_index]
                        labelled = re.search(r"(?:20)?(\d{2})-(\d{2})", root.name)
                        if (
                            sample_years
                            and labelled
                            and f"{labelled[1]}-{labelled[2]}" == parsed["financial_year"]
                        ):
                            sampled_roots.add(record.root_index)
                        entries.append(
                            parsed
                            | {
                                "file_id": record.file_id,
                                "file_name": record.file_name,
                                "path": record.path,
                            }
                        )
                except (OSError, ValueError, RuntimeError):
                    continue
        return entries

    def years(self) -> list[str]:
        return sorted(
            {str(row["financial_year"]) for row in self.entries(sample_years=True)}, reverse=True
        )

    def search(self, year: str, bill: str) -> list[dict[str, Any]]:
        normalized = re.sub(r"\s+", "", bill).upper()
        full = parse_number(normalized)
        if full:
            if full[1] != year:
                raise ValueError("The bill number belongs to a different financial year.")
            serial, series = full[2], full[0]
        elif re.fullmatch(r"\d{1,12}", normalized):
            serial, series = int(normalized), None
        else:
            raise ValueError("Enter a bill number such as 74 or HST/L/26-27/74.")
        matches = [
            row
            for row in self.entries(serial_filter=serial)
            if row["financial_year"] == year
            and row["serial"] == serial
            and (series is None or row["series"] == series)
        ]
        hashes: dict[tuple[str, str], dict[str, Any]] = {}
        for row in matches:
            content = self.scanner.validate_path("bills", row["path"]).read_bytes()
            checksum = hashlib.sha256(content).hexdigest()
            canonical = f"{row['series']}/{row['financial_year']}/{row['serial']}"
            hashes.setdefault((canonical, checksum), row | {"sha256": checksum})
        results = list(hashes.values())
        for row in results:
            row["conflicting_copies"] = (
                sum(
                    (other["series"], other["financial_year"], other["serial"])
                    == (row["series"], row["financial_year"], row["serial"])
                    for other in results
                )
                > 1
            )
        return [self.public(row) for row in results]

    @staticmethod
    def public(row: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in row.items() if key not in {"path", "serial"}}

    def file(self, file_id: str) -> tuple[Path, dict[str, Any]]:
        # Re-scan/re-parse changed files before granting access; no arbitrary paths.
        row = next(iter(self.entries(file_id_filter=file_id)), None)
        if row is None:
            raise ValueError("The saved bill PDF is unavailable or cannot be identified safely.")
        path = self.scanner.validate_path("bills", row["path"])
        if len(self.search(row["financial_year"], row["bill_number"])) > 1:
            raise ValueError("Different PDFs exist for this bill. Ask the office to resolve them.")
        return path, self.public(row)
