"""Exact invoice identity from PDF headers; no BUSY database access."""

from __future__ import annotations

import hashlib
import re
import threading
from pathlib import Path
from typing import Any

import pymupdf

from app.domains.documents.scanner import DocumentScanner

VOUCHER = r"([A-Z]+(?:/[A-Z]+)?)/(\d{2})-(\d{2})/(\d+)"
HEADER = re.compile(
    r"(?:Invoice|Bill|Voucher)\s*(?:No\.?|Number)\s*:?\s*(" + VOUCHER + r")\b", re.I
)
FULL = re.compile(VOUCHER, re.I)


def identity(text: str) -> dict[str, Any] | None:
    matches = list(HEADER.finditer(text))
    numbers = {re.sub(r"\s+", "", match[1]).upper() for match in matches}
    if len(numbers) != 1:
        return None
    number = numbers.pop()
    parsed = FULL.fullmatch(number)
    if parsed is None or (int(parsed[3]) - int(parsed[2])) % 100 != 1:
        return None
    party = re.search(r"Billed\s+to\s*:?\s*(?:Shipped\s+to\s*:?\s*)?([^\r\n]+)", text, re.I)
    dated = re.search(r"\bDated\s*:?\s*(\d{1,2}-\d{1,2}-\d{4})", text, re.I)
    return {
        "bill_number": number,
        "financial_year": f"{parsed[2]}-{parsed[3]}",
        "serial": int(parsed[4]),
        "series": parsed[1].upper(),
        "party_name": party[1].strip() if party else "See PDF for party name",
        "date": dated[1] if dated else "",
    }


class InvoiceCatalogue:
    def __init__(self, scanner: DocumentScanner) -> None:
        self.scanner = scanner
        self._cache: dict[str, tuple[int, int, dict[str, Any] | None]] = {}
        self._lock = threading.Lock()

    def entries(self) -> list[dict[str, Any]]:
        entries = []
        with self._lock:
            for record in self.scanner.scan(categories=["bills"]):
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
        return sorted({str(row["financial_year"]) for row in self.entries()}, reverse=True)

    def search(self, year: str, bill: str) -> list[dict[str, Any]]:
        normalized = re.sub(r"\s+", "", bill).upper()
        full = FULL.fullmatch(normalized)
        if full:
            if f"{full[2]}-{full[3]}" != year:
                raise ValueError("The bill number belongs to a different financial year.")
            serial, series = int(full[4]), full[1].upper()
        elif re.fullmatch(r"\d{1,12}", normalized):
            serial, series = int(normalized), None
        else:
            raise ValueError("Enter a bill number such as 74 or HST/L/26-27/74.")
        matches = [
            row
            for row in self.entries()
            if row["financial_year"] == year
            and row["serial"] == serial
            and (series is None or row["series"] == series)
        ]
        hashes: dict[tuple[str, str], dict[str, Any]] = {}
        for row in matches:
            content = self.scanner.validate_path("bills", row["path"]).read_bytes()
            checksum = hashlib.sha256(content).hexdigest()
            hashes.setdefault((row["bill_number"], checksum), row | {"sha256": checksum})
        results = list(hashes.values())
        for row in results:
            row["conflicting_copies"] = (
                sum(other["bill_number"] == row["bill_number"] for other in results) > 1
            )
        return [self.public(row) for row in results]

    @staticmethod
    def public(row: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in row.items() if key not in {"path", "serial"}}

    def file(self, file_id: str) -> tuple[Path, dict[str, Any]]:
        # Re-scan/re-parse changed files before granting access; no arbitrary paths.
        row = next((item for item in self.entries() if item["file_id"] == file_id), None)
        if row is None:
            raise ValueError("The saved bill PDF is unavailable or cannot be identified safely.")
        path = self.scanner.validate_path("bills", row["path"])
        if len(self.search(row["financial_year"], row["bill_number"])) > 1:
            raise ValueError("Different PDFs exist for this bill. Ask the office to resolve them.")
        return path, self.public(row)
