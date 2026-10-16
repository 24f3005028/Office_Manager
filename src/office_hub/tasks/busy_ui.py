"""Optional, profile-driven BUSY UI export adapter.

No BUSY menu assumptions are embedded here. A machine-specific profile must explicitly describe
the controls/keys for that BUSY version. Until then, the adapter raises a safe configuration error
instead of guessing and potentially editing accounting data.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import TaskContext
from .busy_lock import BusyAutomationLock


class BusyUiConfigurationError(RuntimeError):
    """Raised when a version-specific BUSY UI profile is missing or invalid."""


@dataclass(frozen=True)
class BusyUiProfile:
    report_types: tuple[str, ...]
    window_title_re: str
    report_keys: tuple[str, ...]
    export_keys: tuple[str, ...]
    date_start_control: str | None = None
    date_end_control: str | None = None
    save_dialog_title_re: str | None = None
    save_filename_control: str | None = None
    save_button_title: str = "Save"

    @classmethod
    def load(cls, path: Path) -> BusyUiProfile:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BusyUiConfigurationError(f"Cannot read BUSY UI profile: {path}") from exc
        required = {"report_types", "window_title_re", "report_keys", "export_keys"}
        if not required.issubset(raw):
            raise BusyUiConfigurationError(
                "BUSY UI profile requires window_title_re, report_keys, and export_keys"
            )
        return cls(
            report_types=tuple(str(report) for report in raw["report_types"]),
            window_title_re=str(raw["window_title_re"]),
            report_keys=tuple(str(key) for key in raw["report_keys"]),
            export_keys=tuple(str(key) for key in raw["export_keys"]),
            date_start_control=raw.get("date_start_control"),
            date_end_control=raw.get("date_end_control"),
            save_dialog_title_re=raw.get("save_dialog_title_re"),
            save_filename_control=raw.get("save_filename_control"),
            save_button_title=str(raw.get("save_button_title", "Save")),
        )


class BusyUiExporter:
    """Execute a read-only, profile-driven export in a guarded critical section."""

    def __init__(self, context: TaskContext) -> None:
        self.context = context
        self.logger = logging.getLogger(__name__)

    def export(
        self,
        report_type: str,
        start_date: str,
        end_date: str,
        output_path: Path,
    ) -> Path:
        settings = self.context.settings
        if not settings.busy_automation_enabled:
            raise BusyUiConfigurationError(
                "BUSY UI automation is disabled. Set OFFICE_HUB_BUSY_AUTOMATION_ENABLED=true "
                "only after reviewing a version-specific profile."
            )
        if settings.busy_ui_profile_file is None:
            raise BusyUiConfigurationError("OFFICE_HUB_BUSY_UI_PROFILE_FILE is not configured")
        if settings.busy_exe_path is None:
            raise BusyUiConfigurationError("OFFICE_HUB_BUSY_EXE_PATH is not configured")
        if not settings.busy_exe_path.is_file():
            raise BusyUiConfigurationError(
                f"BUSY executable does not exist: {settings.busy_exe_path}"
            )
        profile = BusyUiProfile.load(settings.busy_ui_profile_file)
        if report_type not in profile.report_types:
            raise BusyUiConfigurationError(
                f"BUSY UI profile is not approved for report type: {report_type}"
            )
        output = output_path.expanduser().resolve()
        if not output.is_relative_to(settings.busy_inbox_dir.resolve()):
            raise BusyUiConfigurationError("BUSY export output must be inside the BUSY inbox")

        try:
            from pywinauto import Desktop  # type: ignore[import-not-found]
            from pywinauto.application import Application  # type: ignore[import-not-found]
        except ImportError as exc:
            raise BusyUiConfigurationError(
                "Install the integrations extra before enabling BUSY UI automation"
            ) from exc

        with BusyAutomationLock(settings.busy_lock_file, timeout_seconds=0):
            desktop = Desktop(backend="uia")
            existing_windows = desktop.windows(title_re=profile.window_title_re)
            if existing_windows:
                raise BusyUiConfigurationError(
                    "BUSY is already open. Close it or use manual .xlsx import; Office Hub "
                    "will not take over an active operator session."
                )
            app = Application(backend="uia").start(str(settings.busy_exe_path))
            window = app.window(title_re=profile.window_title_re)
            window.wait("ready", timeout=settings.busy_automation_timeout_seconds)
            window.set_focus()
            for keys in profile.report_keys:
                window.type_keys(keys, set_foreground=False)
            self._set_date_control(window, profile.date_start_control, start_date)
            self._set_date_control(window, profile.date_end_control, end_date)
            for keys in profile.export_keys:
                window.type_keys(keys, set_foreground=False)
            return self._save_export(window, profile, output)

    @staticmethod
    def _set_date_control(window: Any, control_name: str | None, value: str) -> None:
        if not control_name:
            return
        control = window.child_window(title=control_name)
        control.wait("ready", timeout=15)
        control.set_edit_text(value)

    def _save_export(self, window: Any, profile: BusyUiProfile, output: Path) -> Path:
        if not profile.save_dialog_title_re or not profile.save_filename_control:
            raise BusyUiConfigurationError(
                "BUSY UI profile must define save_dialog_title_re and save_filename_control"
            )
        time.sleep(0.5)
        save_dialog = window.top_level_parent().window(title_re=profile.save_dialog_title_re)
        save_dialog.wait("ready", timeout=self.context.settings.busy_automation_timeout_seconds)
        filename = save_dialog.child_window(title=profile.save_filename_control)
        filename.set_edit_text(str(output))
        save_dialog.child_window(title=profile.save_button_title).click_input()
        if not output.is_file() or output.stat().st_size == 0:
            raise BusyUiConfigurationError("BUSY export did not produce a non-empty workbook")
        return output
