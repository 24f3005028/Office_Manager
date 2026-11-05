"""Guarded desktop report export. Never opens a BUSY database or edits vouchers."""

from __future__ import annotations

import importlib
import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

from app.config import Settings
from app.domains.pouncha_sync.parser import SyncError

FLAGS = ["Y", "Y", "Y", "N", "N", "N", "N", "N", "Y"]
MAX_HOME_ESCAPES = 15


def normalize(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


class BusyExporter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _visible(root: Any, kind: str) -> list[Any]:
        bounds = root.rectangle()
        return [
            control
            for control in root.descendants(control_type=kind)
            if control.is_visible()
            and control.is_enabled()
            and control.rectangle().right > bounds.left
            and control.rectangle().left < bounds.right
            and control.rectangle().bottom > bounds.top
            and control.rectangle().top < bounds.bottom
        ]

    @staticmethod
    def _active_window(main: Any, desktop: Any) -> Any:
        # VB6 exposes owned modal forms beneath the disabled company window in
        # UIA. Desktop.windows() alone does not enumerate these forms.
        roots = list(desktop.windows(process=main.process_id(), visible_only=True))
        roots.extend(main.descendants(control_type="Window"))
        roots.append(main)
        active: dict[int, Any] = {}
        for root in roots:
            if (
                root.handle
                and root.process_id() == main.process_id()
                and root.is_visible()
                and root.is_enabled()
            ):
                active[root.handle] = root
        if len(active) != 1:
            raise SyncError(
                "BUSY's active form could not be identified safely. "
                "The window may be blocked or changing; retry after it finishes."
            )
        return next(iter(active.values()))

    def _is_report(self, root: Any) -> bool:
        return any(
            "refresh report after data modification" in item.window_text().lower()
            for item in self._visible(root, "CheckBox")
        )

    def _buttons(self, root: Any, name: str) -> list[Any]:
        return [
            control
            for control in self._visible(root, "Button")
            if re.fullmatch(name, control.window_text().replace("&", ""), re.I)
        ]

    def _click(self, root: Any, name: str) -> None:
        matches = self._buttons(root, name)
        if len(matches) != 1:
            raise SyncError(
                "BUSY's expected button is unavailable or ambiguous. "
                "Leave BUSY on its homepage and retry."
            )
        matches[0].invoke()

    def _edits(self, root: Any) -> list[Any]:
        controls = [
            control
            for control in self._visible(root, "Edit")
            if control.element_info.name != "Frame1"
        ]
        return sorted(
            controls, key=lambda control: (control.rectangle().top, control.rectangle().left)
        )

    @staticmethod
    def _set(control: Any, value: str) -> None:
        control.set_edit_text(value)
        if control.get_value().strip().casefold() != value.casefold():
            raise SyncError("BUSY did not accept a report field. Export stopped.")

    def _guard(self, main: Any, desktop: Any) -> list[Any]:
        windows = [self._active_window(main, desktop)]
        for window in windows:
            names = " ".join(
                [window.window_text()]
                + [item.window_text() for item in self._visible(window, "Text")]
            )
            if re.search(
                r"unsaved|discard|save changes|save.*voucher|quit.*saving|"
                r"overwrite|delete voucher|exit busy",
                names,
                re.I,
            ):
                raise SyncError(
                    "BUSY has an unsaved-work or confirmation dialog. "
                    "Resolve it manually; no answer was sent."
                )
        return windows

    def _home(self, main: Any, desktop: Any) -> bool:
        for attempt in range(MAX_HOME_ESCAPES + 1):
            windows = self._guard(main, desktop)
            for window in windows:
                if re.search(r"Close Company", window.window_text(), re.I):
                    self._click(window, "No")
                    time.sleep(0.3)
                    return True
            if not windows:
                raise SyncError("BUSY's active form is blocked or unavailable.")
            if attempt == MAX_HOME_ESCAPES:
                return False
            # The user requested bounded Escape navigation through other BUSY
            # screens too. _guard still stops known unsafe confirmations first.
            windows[0].type_keys("{ESC}", pause=0.1)
            time.sleep(0.25)
        return False  # pragma: no cover - the bounded loop always returns above

    def _open_ledger(self, main: Any, desktop: Any) -> tuple[Any, list[Any]]:
        reached_home = self._home(main, desktop)
        # One attempt only, including when Escape could not reach the homepage.
        # Never send Alt+L into a newly appeared unsafe confirmation.
        self._guard(main, desktop)[0].type_keys("%l", pause=0.15)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            target = self._guard(main, desktop)[0]
            edits = self._edits(target)
            if (
                len(edits) == 15
                and self._buttons(target, r"OK\s*\(F2\)")
                and all(
                    re.fullmatch(r"\d{2}-\d{2}-\d{4}", edits[i].get_value().strip()) for i in (2, 3)
                )
                and all(control.get_value().strip() in ("Y", "N") for control in edits[6:])
            ):
                return target, edits
            time.sleep(0.2)
        if not reached_home:
            raise SyncError(
                "BUSY did not open the Account Ledger after 15 Escape presses "
                "and one direct Alt+L attempt. Return to the homepage manually and retry."
            )
        raise SyncError("The Account Ledger options layout changed. No report fields were guessed.")

    def export(self, start: date, end: date, directory: Path) -> Path:
        if sys.platform != "win32":
            raise SyncError("BUSY desktop export requires an interactive Windows session.")
        fy = self.settings.busy_financial_year
        year = 2000 + int(fy.split("-")[0])
        if not date(year, 4, 1) <= start <= end <= date(year + 1, 3, 31):
            raise SyncError(f"Select dates within BUSY's configured financial year {fy}.")
        try:
            desktop = importlib.import_module("pywinauto").Desktop(backend="uia")
            candidates = desktop.windows(title_re=r"(?i)^Busy\s+21\s+Rel\b.*", visible_only=True)
            if len(candidates) != 1:
                raise SyncError("Open one BUSY 21 window and log into H.S. TRADERS before syncing.")
            main = candidates[0]
            title = main.window_text()
            company = re.search(r"\|\s*([^|]+?)\s*\(F\.Y\.", title, re.I)
            if company is None or normalize(company[1]) != normalize(self.settings.pouncha_company):
                raise SyncError("The BUSY window is not logged into the configured company.")
            if f"{year}-{str(year + 1)[-2:]}" not in title:
                raise SyncError("The BUSY financial year does not match the configured year.")
            target, edits = self._open_ledger(main, desktop)
            values = [
                "STANDARD",
                "Sales",
                start.strftime("%d-%m-%Y"),
                end.strftime("%d-%m-%Y"),
                "Single Account (Auto)",
                "Name",
                *FLAGS,
            ]
            for control, value in zip(edits, values, strict=True):
                self._set(control, value)
            # Re-read every field before generating a report.
            if [control.get_value().strip().casefold() for control in edits] != [
                v.casefold() for v in values
            ]:
                raise SyncError("BUSY changed a report option during entry; export stopped.")
            self._click(target, r"OK\s*\(F2\)")
            deadline = time.monotonic() + self.settings.pouncha_export_timeout_seconds
            while time.monotonic() < deadline:
                target = self._guard(main, desktop)[0]
                if self._is_report(target):
                    break
                time.sleep(0.3)
            else:
                raise SyncError("BUSY did not finish generating the Sales ledger.")
            target.type_keys("%e", pause=0.15)
            export_window = None
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                roots = self._guard(main, desktop)
                matches = [
                    root
                    for root in roots
                    if re.fullmatch(r"Export (?:Report )?Data", root.window_text().strip(), re.I)
                    and root.is_enabled()
                ]
                if matches:
                    export_window = matches[0]
                    break
                time.sleep(0.2)
            if export_window is None:
                raise SyncError("BUSY's Export Report Data dialog was not found.")
            fields = self._edits(export_window)
            if len(fields) != 5:
                raise SyncError("BUSY's export controls changed. Use the Excel upload fallback.")
            filename = directory / "sales"
            for control, value in zip(
                fields, ["Microsoft Excel", str(filename), "Zero", "", "Not Reqd."], strict=True
            ):
                self._set(control, value)
            self._click(export_window, "OK")
            previous_size = -1
            stable = 0
            deadline = time.monotonic() + self.settings.pouncha_export_timeout_seconds
            while time.monotonic() < deadline:
                windows = self._guard(main, desktop)
                for window in windows:
                    if re.search(r"Open File Now", window.window_text(), re.I):
                        self._click(window, "No")
                for candidate in (filename.with_suffix(".xlsx"), filename):
                    if candidate.is_file():
                        size = candidate.stat().st_size
                        stable = stable + 1 if size == previous_size and size > 0 else 0
                        previous_size = size
                        if stable >= 3:
                            with candidate.open("rb") as stream:
                                if stream.read(2) != b"PK":
                                    raise SyncError("BUSY did not export an Excel workbook.")
                            # Never return while an export-open prompt still needs an answer.
                            for window in self._guard(main, desktop):
                                if re.search(r"Open File Now", window.window_text(), re.I):
                                    self._click(window, "No")
                            return candidate
                time.sleep(0.5)
            raise SyncError("BUSY did not create an unlocked Excel export in time.")
        except SyncError:
            raise
        except Exception as exc:
            raise SyncError(
                "BUSY export could not complete safely. Leave the company homepage open "
                "and retry, or upload an Excel export."
            ) from exc
