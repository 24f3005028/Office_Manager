"""Ephemeral Excel export from the BUSY desktop UI."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from openpyxl import load_workbook  # type: ignore[import-untyped]

from app.domains.busy_automation.errors import (
    BusyExportError,
    BusyUnsafeStateError,
)
from app.domains.busy_automation.profile import BusyUiProfile
from app.domains.busy_automation.session import (
    BusySessionProtocol,
    title_matches,
)

logger = logging.getLogger(__name__)

SUPPORTED_EXPORT_SUFFIXES = frozenset({".xlsx", ".xlsm", ".xls"})
_EXTENSION_CANDIDATES = ("", ".xlsx", ".xlsm", ".xls")


class BusyExporter:
    """Drive the BUSY export dialog and wait for a stable workbook."""

    def __init__(
        self,
        profile: BusyUiProfile,
        *,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.profile = profile
        self.export_profile = profile.export
        self._sleep = sleep
        self._monotonic = monotonic

    def export(self, session: BusySessionProtocol, target: Path) -> Path:
        target = Path(target)
        if target.suffix.casefold() not in SUPPORTED_EXPORT_SUFFIXES:
            raise BusyExportError(f"Unsupported BUSY export path: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        entry_path = self._entry_path(target)
        candidates = self._candidate_paths(entry_path)
        for candidate in candidates:
            if candidate.exists():
                candidate.unlink()

        logger.info("Exporting the BUSY report to %s", entry_path)
        session.focus()
        session.send_keys(self.export_profile.hotkey)
        dialog = session.wait_for_dialog(
            self.export_profile.dialog_title_re,
            timeout=self.export_profile.dialog_wait_sec,
        )
        session.focus(dialog)
        self._set_format(session, dialog)
        self._set_path(session, dialog, entry_path)
        self._uncheck_open_after(session, dialog)
        session.send_keys(self.export_profile.confirm_keys, window=dialog)
        exported = self._wait_for_file(session, dialog, candidates)
        self._validate_workbook(exported)
        return exported

    def _entry_path(self, target: Path) -> Path:
        """Return the path text BUSY expects.

        BUSY 21 appends ``.xlsx`` itself when the Data Format is Microsoft
        Excel, so the File Name field must be entered without the extension.
        """

        if self.export_profile.append_extension:
            return target.with_suffix("")
        return target

    def _candidate_paths(self, entry_path: Path) -> tuple[Path, ...]:
        if not self.export_profile.append_extension:
            return (entry_path,)
        stem = entry_path
        if stem.suffix.casefold() in SUPPORTED_EXPORT_SUFFIXES:
            stem = stem.with_suffix("")
        candidates = [
            stem.with_name(stem.name + suffix) for suffix in _EXTENSION_CANDIDATES
        ]
        # Prefer .xlsx first so a stale extensionless file cannot win.
        unique: list[Path] = []
        for candidate in sorted(
            candidates, key=lambda item: (item.suffix != ".xlsx", str(item))
        ):
            if candidate not in unique:
                unique.append(candidate)
        return tuple(unique)

    def _set_format(self, session: BusySessionProtocol, dialog: Any) -> None:
        profile = self.export_profile
        if profile.format_control:
            if not session.select_combo_item(
                profile.format_control, profile.format_value
            ):
                raise BusyExportError(
                    "Could not set the BUSY export Data Format to "
                    f"{profile.format_value!r}. Check export.format_control in "
                    "the UI profile."
                )
            return
        if profile.format_keys:
            session.send_keys(profile.format_keys, window=dialog)
            return
        raise BusyExportError(
            "BUSY export Data Format is not calibrated. Set "
            "export.format_control or export.format_keys in "
            "config/busy_ui_profile.json so the export is Microsoft Excel."
        )

    def _set_path(
        self,
        session: BusySessionProtocol,
        dialog: Any,
        entry_path: Path,
    ) -> None:
        profile = self.export_profile
        text = str(entry_path)
        if profile.path_control:
            if not session.set_text(dialog, profile.path_control, text):
                raise BusyExportError(
                    "Could not fill the BUSY export path field. Check "
                    "export.path_control in the UI profile."
                )
            return
        if profile.path_focus_keys:
            session.send_keys(profile.path_focus_keys, window=dialog)
            session.send_keys("^a", window=dialog)
            session.type_text(text, window=dialog)
            return
        if profile.auto_detect_path_control:
            edits = session.find_children(dialog, {"class_name": "Edit"})
            if len(edits) == 1:
                if not session.set_control_text(edits[0], text):
                    raise BusyExportError(
                        "Could not fill the only edit field in the BUSY export dialog."
                    )
                return
            if len(edits) > 1:
                descriptions = [session.window_title(edit) for edit in edits]
                raise BusyExportError(
                    "The BUSY export dialog has "
                    f"{len(edits)} edit fields; set export.path_control in "
                    f"config/busy_ui_profile.json. Fields: {descriptions}"
                )
        raise BusyExportError(
            "BUSY export path entry is not calibrated. Set export.path_control "
            "or export.path_focus_keys in config/busy_ui_profile.json."
        )

    def _uncheck_open_after(
        self, session: BusySessionProtocol, dialog: Any
    ) -> None:
        profile = self.export_profile
        if profile.open_after_control:
            controls = session.find_children(dialog, profile.open_after_control)
            if not controls:
                raise BusyExportError(
                    "Could not find the 'Open file after export' checkbox. "
                    "Check export.open_after_control in the UI profile."
                )
            if not session.uncheck(controls[0]):
                raise BusyExportError(
                    "Could not clear the 'Open file after export' checkbox."
                )
            return
        if not profile.auto_detect_open_after_control:
            return
        candidates = session.find_children(
            dialog,
            {
                "class_name": "Button",
                "title_re": r"(?i).*open.*(file|export|after).*",
            },
        )
        if len(candidates) == 1:
            if not session.uncheck(candidates[0]):
                logger.warning(
                    "Could not clear the auto-detected 'Open file after export' checkbox."
                )

    def _wait_for_file(
        self,
        session: BusySessionProtocol,
        export_dialog: Any,
        candidates: tuple[Path, ...],
    ) -> Path:
        profile = self.export_profile
        deadline = self._monotonic() + profile.file_ready_timeout_sec
        handled: set[int] = set()
        signatures: dict[Path, tuple[int, int]] = {}
        stable_since: dict[Path, float] = {}
        while True:
            self._handle_post_export_dialogs(session, export_dialog, handled)
            for candidate in candidates:
                try:
                    stat = candidate.stat()
                    signature = (stat.st_size, stat.st_mtime_ns)
                except OSError:
                    continue
                if signature[0] <= 0:
                    continue
                now = self._monotonic()
                if signatures.get(candidate) != signature:
                    signatures[candidate] = signature
                    stable_since[candidate] = now
                    continue
                started = stable_since.get(candidate)
                if started is not None and now - started >= profile.file_stable_sec:
                    return candidate
            if self._monotonic() >= deadline:
                titles = [
                    session.window_title(window)
                    for window in session.visible_dialogs()
                ]
                expected = ", ".join(str(item) for item in candidates)
                raise BusyExportError(
                    "BUSY did not create a stable Excel export at "
                    f"{expected} within {profile.file_ready_timeout_sec:.1f}s. "
                    f"Visible windows: {titles or 'none'}."
                )
            self._sleep(0.2)

    def _handle_post_export_dialogs(
        self,
        session: BusySessionProtocol,
        export_dialog: Any,
        handled: set[int],
    ) -> None:
        profile = self.export_profile
        export_handle = session.window_handle(export_dialog)
        for dialog in session.visible_dialogs():
            handle = session.window_handle(dialog)
            if handle in handled or handle == export_handle:
                continue
            title = session.window_title(dialog)
            if title_matches(self.profile.unsafe_dialog_re, title):
                raise BusyUnsafeStateError(
                    "BUSY showed a dialog during export that may discard or "
                    f"overwrite data: {title!r}. Automation stopped."
                )
            if title_matches(self.profile.exit_dialog_re, title):
                raise BusyUnsafeStateError(
                    "BUSY showed an exit confirmation dialog during export: "
                    f"{title!r}."
                )
            if profile.open_after_dialog_title_re and title_matches(
                profile.open_after_dialog_title_re, title
            ):
                if not profile.open_after_keys:
                    raise BusyUnsafeStateError(
                        "BUSY asked to open the exported file, but "
                        "export.open_after_keys is not configured."
                    )
                session.send_keys(profile.open_after_keys, window=dialog)
                handled.add(handle)
                continue
            if title_matches(profile.success_title_re, title):
                if profile.success_dismiss_keys:
                    session.send_keys(
                        profile.success_dismiss_keys, window=dialog
                    )
                handled.add(handle)
                continue
            if any(
                title_matches(pattern, title)
                for pattern in self.profile.allowed_dialog_title_res
            ):
                if self.profile.allowed_dialog_dismiss_keys:
                    session.send_keys(
                        self.profile.allowed_dialog_dismiss_keys,
                        window=dialog,
                    )
                handled.add(handle)
                continue
            raise BusyUnsafeStateError(
                f"Unexpected BUSY dialog during export: {title!r}. "
                "Automation stopped without answering it."
            )

    def _validate_workbook(self, target: Path) -> None:
        if not target.is_file() or target.stat().st_size == 0:
            raise BusyExportError(f"BUSY created an empty export file: {target}")
        with target.open("rb") as handle:
            magic = handle.read(8)
        is_zip = magic.startswith(b"PK\x03\x04")
        is_ole = magic.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
        try:
            if is_zip:
                # Pass a file object so openpyxl does not reject an
                # extensionless BUSY export based on its filename.
                with target.open("rb") as handle:
                    workbook = load_workbook(
                        handle, read_only=True, data_only=True
                    )
                    try:
                        if not workbook.sheetnames:
                            raise BusyExportError(
                                "The BUSY export contains no worksheets."
                            )
                    finally:
                        workbook.close()
            elif is_ole:
                import xlrd  # type: ignore[import-untyped]

                workbook = xlrd.open_workbook(target, on_demand=True)
                try:
                    if workbook.nsheets == 0:
                        raise BusyExportError(
                            "The BUSY export contains no worksheets."
                        )
                finally:
                    workbook.release_resources()
            else:
                raise BusyExportError(
                    "The BUSY export is not a readable Excel workbook: "
                    "unrecognized file signature."
                )
        except BusyExportError:
            raise
        except Exception as exc:
            raise BusyExportError(
                f"The BUSY export is not a readable Excel workbook: {exc}"
            ) from exc
