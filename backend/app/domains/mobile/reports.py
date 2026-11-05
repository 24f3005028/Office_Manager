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
        or normalize(account[1]) != normalize(party)
        or status is None
        or parse(status[1]) != as_of
        or dates is None
        or parse(dates[1]) != REPORT_START
        or parse(dates[2]) != as_of
    ):
        raise SyncError("The PDF party or report dates did not match. It was not shared.")
    for heading in ("S.No.", "Dated", "Ref. No.", "Ref. Amt.", "Pending Amt.", "Due Days"):
        if heading not in flat:
            raise SyncError("BUSY's report columns changed. Check the print-from-grid settings.")
    totals = re.search(r"Grand Total\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})", flat, re.I)
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
        if not self._home(main, desktop):
            raise SyncError("BUSY could not return to its homepage safely.")
        # The supplied BUSY favourite list has Outstanding Bills in fourth position.
        # Never enter options until the expected One Account dialog is confirmed.
        target = self._guard(main, desktop)[0]
        favourites = [
            button for button in self._visible(target, "Button") if button.window_text() == "TVFAV"
        ]
        if len(favourites) != 1:
            raise SyncError("BUSY's Favourites control was not found.")
        favourites[0].invoke()
        target.type_keys("{HOME}{DOWN 3}{ENTER}", pause=0.2)
        target = self._wait(main, desktop, lambda root: bool(self._buttons(root, "One Account")))
        self._click(target, "One Account")
        target = self._wait(main, desktop, lambda root: len(self._edits(root)) == 19)
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
        target.type_keys("%p", pause=0.2)
        target = self._wait(
            main, desktop, lambda root: bool(self._buttons(root, "As it is From Grid"))
        )
        self._click(target, "As it is From Grid")
        target = self._wait(main, desktop, lambda root: bool(self._buttons(root, "Default")))
        # Keep the demonstrated saved grid layout; the final PDF verifier enforces it.
        self._click(target, "OK")
        target = self._wait(main, desktop, lambda root: bool(self._buttons(root, "Preview")))
        self._click(target, "Preview")
        target = self._wait(main, desktop, lambda root: "Print Preview" in root.window_text())
        pdf_buttons = [
            button
            for button in self._visible(target, "Button")
            if re.search(r"(?:save|export).*PDF|PDF.*(?:save|export)", button.window_text(), re.I)
        ]
        if len(pdf_buttons) != 1:
            raise SyncError("BUSY's PDF save control needs calibration. No document was shared.")
        pdf_buttons[0].invoke()
        target = self._wait(main, desktop, lambda root: bool(self._buttons(root, "Save")))
        fields = self._edits(target)
        name_fields = [
            field for field in fields if re.search(r"file name", field.element_info.name, re.I)
        ]
        if len(name_fields) != 1:
            raise SyncError("BUSY's Save PDF filename field could not be identified.")
        path = directory / "outstanding.pdf"
        self._set(name_fields[0], str(path))
        self._click(target, "Save")
        previous = -1
        stable = 0
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if path.is_file():
                size = path.stat().st_size
                stable = stable + 1 if size > 0 and size == previous else 0
                previous = size
                if stable >= 3:
                    verify_report(path, party, as_of)
                    return path
            time.sleep(0.4)
        raise SyncError("BUSY did not finish saving the PDF in time.")
