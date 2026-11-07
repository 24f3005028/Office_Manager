"""Native BUSY report adapter and verification of the resulting PDF."""

from __future__ import annotations

import importlib
import re
import sys
import time
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pymupdf

from app.domains.pouncha_sync.busy import BusyExporter, normalize
from app.domains.pouncha_sync.parser import SyncError

REPORT_START = date(2025, 1, 16)


def statement_filename(party: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", party).strip(" .")[:140].rstrip(" .")
    if not name or re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", name, re.I):
        name = "Party " + name
    return name + ".pdf"


def verify_report(path: Path, party: str, as_of: date) -> dict[str, Any]:
    if not path.is_file() or not 0 < path.stat().st_size <= 25 * 1024 * 1024:
        raise SyncError("BUSY did not create a usable report PDF.")
    with pymupdf.open(path) as pdf:  # type: ignore[no-untyped-call]
        if pdf.is_encrypted or not pdf.page_count:
            raise SyncError("The report PDF is empty or locked.")
        text = "\n".join(str(page.get_text()) for page in pdf)
        pages = pdf.page_count
    flat = re.sub(r"\s+", " ", text)
    account = re.search(r"Account\s*:\s*(.*?)\s+On Basis", flat, re.I)
    status = re.search(r"Bills Status as on\s*:\s*(\d{1,2}-\d{1,2}-\d{4})", flat, re.I)
    dates = re.search(
        r"From\s+(\d{1,2}-\d{1,2}-\d{4})\s+to\s+"
        r"(\d{1,2}-\d{1,2}-\d{4})",
        flat,
        re.I,
    )

    def parse(value: str) -> date:
        day, month, year = (int(part) for part in value.split("-"))
        return date(year, month, day)

    if (
        "Bills Receivable" not in flat
        or "H.S. TRADERS" not in flat
        or account is None
        or re.sub(r"\s+", " ", account[1]).strip().casefold()
        != re.sub(r"\s+", " ", party).strip().casefold()
        or status is None
        or parse(status[1]) != as_of
        or dates is None
        or parse(dates[1]) != REPORT_START
        or parse(dates[2]) != as_of
    ):
        raise SyncError("The PDF party or report dates did not match. It was not shared.")
    for heading in ("Dated", "Ref. No.", "Ref. Amt.", "Pending Amt."):
        if heading not in flat:
            raise SyncError("BUSY's report columns changed. Check the outstanding export settings.")
    printed = "S.No." in flat and "Due Days" in flat
    exported = "Type" in flat and "Due Date" in flat and "Due Day" in flat
    if not (printed or exported):
        raise SyncError("The PDF is not a supported BUSY outstanding report layout.")
    total_label = r"Grand Total" if printed else r"(?<!\w)Total"
    totals = re.search(
        total_label + r"\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+(?:\(\s*)?On Acc\.",
        flat,
        re.I,
    )
    if totals is None:
        raise SyncError("The PDF totals could not be verified. It was not shared.")
    pending = Decimal(totals[2].replace(",", ""))
    return {
        "party_name": party,
        "as_of": as_of.isoformat(),
        "start_date": REPORT_START.isoformat(),
        "pending_amount": str(pending),
        "reference_amount": totals[1].replace(",", ""),
        "pages": pages,
    }


class OutstandingExporter(BusyExporter):
    def _pdf_filename(self, party: str) -> str:
        return statement_filename(party)

    def _verify_export_pdf(self, path: Path, party: str, as_of: date) -> Any:
        return verify_report(path, party, as_of)

    def _wait(self, main: Any, desktop: Any, predicate: Any, seconds: float = 12) -> Any:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            target = self._guard(main, desktop)[0]
            if predicate(target):
                return target
            time.sleep(0.2)
        raise SyncError("BUSY did not reach the expected report screen. No fields were guessed.")

    def export_report(self, party: str, as_of: date, directory: Path) -> Path:
        if sys.platform != "win32":
            raise SyncError("An unlocked Windows desktop is required for BUSY reports.")
        desktop = importlib.import_module("pywinauto").Desktop(backend="uia")
        candidates = desktop.windows(title_re=r"(?i)^Busy\s+21\s+Rel\b.*", visible_only=True)
        if len(candidates) != 1:
            raise SyncError("Open one BUSY 21 company window before requesting a fresh report.")
        main = candidates[0]
        company = re.search(r"\|\s*([^|]+?)\s*\(F\.Y\.", main.window_text(), re.I)
        if company is None or normalize(company[1]) != normalize(self.settings.pouncha_company):
            raise SyncError("BUSY must be logged into H.S. TRADERS.")
        target = self._open_outstanding(main, desktop)
        edits = self._edits(target)
        # Group the two columns; screen scaling affects coordinates, not relative order.
        left_edge, right_edge = (
            min(e.rectangle().left for e in edits),
            max(e.rectangle().left for e in edits),
        )
        middle = (left_edge + right_edge) / 2
        left = sorted(
            [e for e in edits if e.rectangle().left < middle], key=lambda e: e.rectangle().top
        )
        right = sorted(
            [e for e in edits if e.rectangle().left >= middle], key=lambda e: e.rectangle().top
        )
        if len(left) != 9 or len(right) != 10:
            raise SyncError("BUSY's outstanding report options changed. Export stopped.")
        day = as_of.strftime("%d-%m-%Y")
        values = [
            "STANDARD",
            party,
            "N",
            "Pending",
            "16-01-2025",
            day,
            day,
            "Name",
            "0",
            "Y",
            "N",
            "N",
            "N",
            "N",
            "N",
            "N",
            "N",
            "N",
            "D",
        ]
        for control, value in zip(left + right, values, strict=True):
            self._set(control, value)
        if [e.get_value().strip().casefold() for e in left + right] != [
            value.casefold() for value in values
        ]:
            raise SyncError("BUSY did not retain the requested party or report options.")
        self._click(target, r"OK\s*\(F2\)")
        target = self._wait(
            main, desktop, self._is_report, self.settings.pouncha_export_timeout_seconds
        )
        return self._export_pdf(main, desktop, target, directory, party, as_of)

    def _open_outstanding(self, main: Any, desktop: Any) -> Any:
        if not self._home(main, desktop):
            raise SyncError("BUSY did not return to its homepage after 15 Escape presses.")
        self._guard(main, desktop)[0].type_keys("%f", pause=0.2)
        # Select by initial, not by the saved favourite's row position.
        self._guard(main, desktop)[0].type_keys("o", pause=0.2)
        self._guard(main, desktop)[0].type_keys("{ENTER}", pause=0.2)
        target = self._wait(main, desktop, lambda root: bool(self._buttons(root, "One Account")))
        self._click(target, "One Account")
        return self._wait(main, desktop, lambda root: len(self._edits(root)) == 19)

    def _export_pdf(
        self, main: Any, desktop: Any, target: Any, directory: Path, party: str, as_of: date
    ) -> Path:
        target.type_keys("%e", pause=0.2)
        target = self._wait(
            main,
            desktop,
            lambda root: bool(re.fullmatch(r"Export (?:Report )?Data", root.window_text(), re.I)),
        )
        fields = self._edits(target)
        if len(fields) < 2:
            raise SyncError("BUSY's export format and filename controls could not be identified.")
        format_fields = [
            field
            for field in fields
            if field.get_value().strip()
            in {
                "Microsoft Excel",
                "Google Sheet",
                "PDF",
                "HTML",
                "CSV",
                "Text File - Delimited",
                "Text File - Fixed Width",
            }
        ]
        if len(format_fields) != 1 or format_fields[0] is not fields[0]:
            raise SyncError("BUSY's export format selector is unavailable or ambiguous.")
        format_fields[0].type_keys("p{ENTER}", pause=0.2)
        # Changing format disables Excel-only fields. Read the layout again.
        target = self._wait(
            main,
            desktop,
            self._is_pdf_export,
        )
        fields = self._edits(target)
        if fields[0].get_value().strip().upper() != "PDF":
            raise SyncError("BUSY did not retain PDF as the export format.")
        path = directory / self._pdf_filename(party)
        if path.exists():
            raise SyncError("The report destination already exists; it was not overwritten.")
        self._set(fields[1], str(path))
        self._click(target, "OK")
        previous = -1
        stable = 0
        deadline = time.monotonic() + self.settings.pouncha_export_timeout_seconds
        while time.monotonic() < deadline:
            for window in self._guard(main, desktop):
                if re.search(r"Open File Now", window.window_text(), re.I):
                    self._click(window, "No")
            if path.is_file():
                size = path.stat().st_size
                stable = stable + 1 if size > 0 and size == previous else 0
                previous = size
                if stable >= 3:
                    self._verify_export_pdf(path, party, as_of)
                    return path
            time.sleep(0.4)
        raise SyncError("BUSY did not finish saving the PDF in time.")

    def _is_pdf_export(self, root: Any) -> bool:
        fields = self._edits(root)
        # Ledger PDFs also expose Attach Link=None after the optional password.
        # These are read-only checks: never write a password or enable a link.
        return (
            2 <= len(fields) <= 4
            and fields[0].get_value().strip().casefold() == "pdf"
            and all(field.get_value().strip().casefold() in {"", "none"} for field in fields[2:])
        )
