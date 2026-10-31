from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from app.domains.busy_automation import lock as lock_module
from app.domains.busy_automation.errors import (
    BusyAutomationError,
    BusyExportError,
    BusyLockTimeoutError,
    BusyUnsafeStateError,
    BusyUserActiveError,
    BusyWrongCompanyError,
)
from app.domains.busy_automation.exporter import BusyExporter
from app.domains.busy_automation.lock import (
    acquire_busy_lock,
    wait_for_user_idle,
)
from app.domains.busy_automation.pipeline import (
    BusyAutomationConfig,
    BusyAutomationPipeline,
    BusyAutomationRequest,
)
from app.domains.busy_automation.profile import (
    BusyRecipeProfile,
    BusyUiProfile,
    load_profile,
)
from app.domains.busy_automation.recipes import (
    AccountLedgerSalesRecipe,
    AccountLedgerSalesReturnRecipe,
    PurchaseReturnRecipe,
    ReportRequest,
    SalesRegisterRecipe,
    recipe_for_category,
)
from app.domains.busy_automation.session import (
    BusySession,
    _connect,
    title_matches,
    verify_company_title,
)
from openpyxl import Workbook


class FakeSummary:
    def __init__(
        self,
        *,
        rows_found: int = 2,
        rows_imported: int = 2,
        warnings: tuple[str, ...] = (),
    ) -> None:
        self.rows_found = rows_found
        self.rows_imported = rows_imported
        self.warnings = warnings


class FakeDialog:
    def __init__(self, title: str) -> None:
        self.title = title
        self.handle = id(self)


class SessionWindow:
    def __init__(
        self,
        title: str,
        *,
        handle: int,
        class_name: str = "Fake",
        visible: bool = True,
    ) -> None:
        self.title = title
        self.handle = handle
        self.class_name_value = class_name
        self.visible = visible
        self.focused = False

    def window_text(self) -> str:
        return self.title

    def class_name(self) -> str:
        return self.class_name_value

    def is_visible(self) -> bool:
        return self.visible

    def is_minimized(self) -> bool:
        return False

    def set_focus(self) -> None:
        self.focused = True

    def descendants(self, **kwargs: Any) -> list[Any]:
        return []

    def process_id(self) -> int:
        return 1


class SessionApp:
    def __init__(self, windows: list[SessionWindow]) -> None:
        self._windows = windows

    def windows(self) -> list[SessionWindow]:
        return list(self._windows)


def make_session(
    main: SessionWindow,
    windows: list[SessionWindow],
    *,
    sent: list[str],
    profile: BusyUiProfile | None = None,
) -> BusySession:
    def send_keys_impl(keys: str, **kwargs: Any) -> None:
        sent.append(keys)

    return BusySession(
        SessionApp([main, *windows]),
        main,
        profile=profile or BusyUiProfile(),
        timeout=1.0,
        send_keys_impl=send_keys_impl,
    )


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.timeout = 1.0
        self._dialogs: list[FakeDialog] = []
        self._children: list[Any] = []

    def ensure_main_menu(self) -> None:
        self.calls.append(("ensure_main_menu",))

    def focus(self, window: Any | None = None) -> None:
        self.calls.append(("focus", window))

    def send_keys(self, keys: str, *, window: Any | None = None) -> None:
        self.calls.append(("send_keys", keys, window))

    def type_text(self, text: str, *, window: Any | None = None) -> None:
        self.calls.append(("type_text", text, window))

    def wait_for_dialog(self, title_re: str, timeout: float) -> Any:
        self.calls.append(("wait_for_dialog", title_re, timeout))
        for dialog in self._dialogs:
            if title_matches(title_re, dialog.title):
                return dialog
        raise AssertionError(f"No dialog matched {title_re!r}")

    def find_dialog(self, title_re: str) -> Any | None:
        for dialog in self._dialogs:
            if title_matches(title_re, dialog.title):
                return dialog
        return None

    def visible_dialogs(self) -> list[Any]:
        return list(self._dialogs)

    def wait_for_title(self, title_re: str, timeout: float) -> str:
        self.calls.append(("wait_for_title", title_re, timeout))
        return title_re

    def set_text(
        self, window: Any, spec: dict[str, Any], text: str
    ) -> bool:
        self.calls.append(("set_text", window, spec, text))
        return True

    def set_text_anywhere(self, spec: dict[str, Any], text: str) -> bool:
        self.calls.append(("set_text_anywhere", spec, text))
        return True

    def set_control_text(self, control: Any, text: str) -> bool:
        self.calls.append(("set_control_text", control, text))
        return True

    def click(self, window: Any, spec: dict[str, Any]) -> bool:
        self.calls.append(("click", window, spec))
        return True

    def uncheck(self, control: Any) -> bool:
        self.calls.append(("uncheck", control))
        return True

    def set_checkbox(self, spec: dict[str, Any], checked: bool) -> bool:
        self.calls.append(("set_checkbox", spec, checked))
        return True

    def select_combo_item(self, spec: dict[str, Any], value: str) -> bool:
        self.calls.append(("select_combo_item", spec, value))
        return True

    def find_children(
        self, window: Any, spec: dict[str, Any]
    ) -> list[Any]:
        self.calls.append(("find_children", window, spec))
        return list(self._children)

    def window_title(self, window: Any) -> str:
        return str(getattr(window, "title", ""))

    def window_handle(self, window: Any) -> int:
        return int(getattr(window, "handle", id(window)))

    def close(self) -> None:
        self.calls.append(("close",))


class ExportFakeSession(FakeSession):
    """A fake session that creates the workbook when the export is confirmed."""

    def __init__(self, target: Path) -> None:
        super().__init__()
        self.target = target
        self.export_dialog = FakeDialog("Export Sales Register")
        self.open_dialog = FakeDialog("Export complete - Open file?")
        self.success_dialog = FakeDialog("Export saved successfully")
        self._dialogs = [self.export_dialog]
        self._children = [object()]

    def send_keys(self, keys: str, *, window: Any | None = None) -> None:
        super().send_keys(keys, window=window)
        if keys == "{ENTER}" and window is self.export_dialog:
            make_workbook(self.target)
            self._dialogs = [self.open_dialog]
        elif keys == "n" and window is self.open_dialog:
            self._dialogs = [self.success_dialog]
        elif keys == "{ENTER}" and window is self.success_dialog:
            self._dialogs = []


class FakeExporter:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, Path]] = []
        self.last_target: Path | None = None

    def export(self, session: Any, target: Path) -> Path:
        self.calls.append((session, target))
        self.last_target = target
        make_workbook(target)
        return target


class FakeRecipe:
    category = "bills"

    def __init__(self) -> None:
        self.requests: list[ReportRequest] = []

    def open_report(self, session: Any, request: ReportRequest) -> None:
        self.requests.append(request)


class FakeImporter:
    def __init__(self, *, delete: bool = True, fail: bool = False) -> None:
        self.calls: list[tuple[tuple[Path, ...], str | None, bool]] = []
        self.delete = delete
        self.fail = fail

    def import_workbooks(
        self,
        paths: list[Path],
        *,
        category: str | None = None,
        dry_run: bool = False,
    ) -> FakeSummary:
        self.calls.append((tuple(paths), category, dry_run))
        if self.fail:
            raise RuntimeError("parse failed")
        if self.delete:
            for path in paths:
                path.unlink(missing_ok=True)
        return FakeSummary()


def make_workbook(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Vch Date", "Vch No.", "Vch Type", "Party Name"])
    sheet.append(
        [date(2026, 10, 25), "HST/26-27/1012", "Sales", "ABC TEXTILES"]
    )
    workbook.save(path)


def make_config(
    tmp_path: Path, *, profile: BusyUiProfile | None = None
) -> BusyAutomationConfig:
    return BusyAutomationConfig(
        executable_path=tmp_path / "Busy21.exe",
        window_title_re=r".*BUSY.*",
        expected_company="H.S. Traders",
        timeout_seconds=1.0,
        idle_seconds=0.0,
        temp_dir=tmp_path / "automation",
        lock_path=tmp_path / "busy.lock",
        profile=profile or BusyUiProfile(),
    )


def test_profile_defaults_when_the_file_is_missing(tmp_path: Path) -> None:
    profile = load_profile(tmp_path / "missing.json")

    assert profile.export.hotkey == "%e"
    assert profile.sales_register.navigation_keys == []
    assert profile.exit_no_keys == "n"
    assert "Save changes" in profile.unsafe_dialog_re


def test_profile_ignores_extra_keys_and_reads_calibration(
    tmp_path: Path,
) -> None:
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps(
            {
                "sales_register": {
                    "navigation_keys": ["{ALT}m", "r"],
                    "start_date_control": {"class_name": "Edit", "control_id": 7},
                },
                "export": {"path_control": {"class_name": "Edit"}},
                "unknown_key": True,
            }
        ),
        encoding="utf-8",
    )

    profile = load_profile(path)

    assert profile.sales_register.navigation_keys == ["{ALT}m", "r"]
    assert profile.sales_register.start_date_control == {
        "class_name": "Edit",
        "control_id": 7,
    }
    assert profile.export.path_control == {"class_name": "Edit"}


def test_profile_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(BusyAutomationError):
        load_profile(path)


def test_company_title_guard_accepts_case_and_punctuation_variants() -> None:
    verify_company_title(
        "BUSY Accounting Software - H.S. Traders", "H.S. Traders"
    )
    verify_company_title("BUSY 21 - H S Traders", "H.S. Traders")
    verify_company_title("BUSY 21 - h.s. traders", "H.S. Traders")
    verify_company_title("Any window", "")


def test_company_title_guard_rejects_another_company() -> None:
    with pytest.raises(BusyWrongCompanyError):
        verify_company_title("BUSY 21 - Other Traders", "H.S. Traders")


def test_title_matches_is_case_insensitive() -> None:
    assert title_matches(r".*Export.*", "Export Sales Register")
    assert not title_matches(r".*Export.*", "Sales Register")


def test_connect_falls_back_to_a_window_handle(tmp_path: Path) -> None:
    class FakeWindow:
        handle = 4242

    class FakeDesktop:
        def __init__(self, *, backend: str) -> None:
            assert backend == "win32"

        def window(self, **kwargs: Any) -> FakeWindow:
            assert "timeout" not in kwargs
            assert kwargs["title_re"] == ".*BUSY.*"
            return FakeWindow()

    class FakeApplication:
        def __init__(self, *, backend: str) -> None:
            assert backend == "win32"

        def connect(self, **kwargs: Any) -> str:
            if "path" in kwargs:
                raise RuntimeError("BUSY is running from another path")
            assert kwargs["handle"] == 4242
            assert kwargs["timeout"] == 1.0
            return "attached"

    result = _connect(
        FakeApplication, FakeDesktop, tmp_path / "Busy21.exe", ".*BUSY.*", 1.0
    )

    assert result == "attached"


def test_session_reset_cancels_an_exit_prompt() -> None:
    main = SessionWindow("BUSY - H.S. Traders", handle=1)
    exit_dialog = SessionWindow("Quit BUSY?", handle=2)
    sent: list[str] = []
    session = make_session(main, [exit_dialog], sent=sent)

    session.ensure_main_menu()

    assert sent == ["n"]


def test_session_reset_refuses_an_unknown_dialog() -> None:
    main = SessionWindow("BUSY - H.S. Traders", handle=1)
    unknown = SessionWindow("Printer not ready", handle=2)
    sent: list[str] = []
    session = make_session(main, [unknown], sent=sent)

    with pytest.raises(BusyUnsafeStateError, match="unexpected"):
        session.ensure_main_menu()


def test_session_reset_refuses_a_save_changes_dialog() -> None:
    main = SessionWindow("BUSY - H.S. Traders", handle=1)
    save_dialog = SessionWindow("Save changes?", handle=2)
    sent: list[str] = []
    session = make_session(main, [save_dialog], sent=sent)

    with pytest.raises(BusyUnsafeStateError, match="discard"):
        session.ensure_main_menu()


def test_session_reset_sends_escape_twice_when_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.domains.busy_automation.session.time.sleep",
        lambda _: None,
    )
    main = SessionWindow("BUSY - H.S. Traders", handle=1)
    sent: list[str] = []
    session = make_session(main, [], sent=sent)

    session.ensure_main_menu()

    assert sent == ["{ESC}", "{ESC}"]


def test_session_visible_dialogs_excludes_menus_and_the_main_window() -> None:
    main = SessionWindow("BUSY - H.S. Traders", handle=1)
    menu = SessionWindow("Menu", handle=2, class_name="#32768")
    dialog = SessionWindow("Export Sales Register", handle=3)
    session = make_session(main, [menu, dialog], sent=[])

    assert [window.title for window in session.visible_dialogs()] == [
        "Export Sales Register"
    ]


class PlainControl:
    def __init__(self) -> None:
        self.clicked = False

    def click_input(self) -> None:
        self.clicked = True

    def click(self) -> None:
        self.clicked = True


class CheckControl:
    def __init__(self, state: int) -> None:
        self.state = state
        self.clicked = False

    def get_toggle_state(self) -> int:
        return self.state

    def click_input(self) -> None:
        self.clicked = True

    def window_text(self) -> str:
        return "Open file after export"


def test_session_uncheck_refuses_a_plain_button() -> None:
    main = SessionWindow("BUSY - H.S. Traders", handle=1)
    session = make_session(main, [], sent=[])
    control = PlainControl()

    assert session.uncheck(control) is False
    assert control.clicked is False


def test_session_uncheck_clicks_only_a_checked_checkbox() -> None:
    main = SessionWindow("BUSY - H.S. Traders", handle=1)
    session = make_session(main, [], sent=[])
    checked = CheckControl(1)
    unchecked = CheckControl(0)

    assert session.uncheck(checked) is True
    assert checked.clicked is True
    assert session.uncheck(unchecked) is True
    assert unchecked.clicked is False


def test_session_wait_for_dialog_stops_on_an_exit_prompt() -> None:
    main = SessionWindow("BUSY - H.S. Traders", handle=1)
    exit_dialog = SessionWindow("Quit BUSY?", handle=2)
    session = make_session(main, [exit_dialog], sent=[])

    with pytest.raises(BusyUnsafeStateError, match="exit"):
        session.wait_for_dialog("Export", timeout=0.1)


def test_session_wait_for_dialog_refuses_a_save_changes_prompt() -> None:
    main = SessionWindow("BUSY - H.S. Traders", handle=1)
    save_dialog = SessionWindow("Save changes before export?", handle=2)
    session = make_session(main, [save_dialog], sent=[])

    with pytest.raises(BusyUnsafeStateError, match="discard"):
        session.wait_for_dialog(".*Export.*", timeout=0.1)


def test_session_wait_for_title_matches_the_main_window() -> None:
    main = SessionWindow("Sales Register", handle=1)
    session = make_session(main, [], sent=[])

    assert session.wait_for_title(r".*Sales Register.*", timeout=0.1) == (
        "Sales Register"
    )


def test_session_wait_for_title_stops_on_a_save_changes_prompt() -> None:
    main = SessionWindow("BUSY - H.S. Traders", handle=1)
    save_dialog = SessionWindow("Save changes?", handle=2)
    session = make_session(main, [save_dialog], sent=[])

    with pytest.raises(BusyUnsafeStateError, match="discard"):
        session.wait_for_title("Sales Register", timeout=0.1)


def test_sales_register_recipe_sends_navigation_and_dates() -> None:
    profile = BusyRecipeProfile(
        navigation_keys=["{ALT}m", "r"],
        navigation_titles=["Menu", "Sales Register"],
        start_date_focus_keys="{TAB}",
        end_date_focus_keys="{TAB}",
        load_keys="{F2}",
        ready_title_re="Sales Register",
        wait_timeout_sec=2.0,
        date_commit_keys="{TAB}",
    )
    session = FakeSession()
    recipe = SalesRegisterRecipe(profile, sleep=lambda _: None)

    recipe.open_report(
        session,
        ReportRequest(date(2026, 10, 1), date(2026, 10, 31)),
    )

    keys = [call[1] for call in session.calls if call[0] == "send_keys"]
    assert keys == [
        "{ALT}m",
        "r",
        "{TAB}",
        "^a",
        "01-10-2026",
        "{TAB}",
        "{TAB}",
        "^a",
        "31-10-2026",
        "{TAB}",
        "{F2}",
    ]
    waits = [call[1] for call in session.calls if call[0] == "wait_for_title"]
    assert waits == ["Menu", "Sales Register", "Sales Register"]
    assert session.calls[0] == ("focus", None)


def test_sales_register_recipe_refuses_uncalibrated_navigation() -> None:
    recipe = SalesRegisterRecipe(BusyRecipeProfile())

    with pytest.raises(BusyAutomationError, match="not calibrated"):
        recipe.open_report(
            FakeSession(),
            ReportRequest(date(2026, 10, 1), date(2026, 10, 31)),
        )


def test_sales_register_recipe_uses_a_series_control() -> None:
    profile = BusyRecipeProfile(
        navigation_keys=["{ALT}m"],
        series_control={"title": "Series"},
        start_date_control={"title": "From"},
        end_date_control={"title": "To"},
    )
    session = FakeSession()
    recipe = SalesRegisterRecipe(profile, sleep=lambda _: None)

    recipe.open_report(
        session,
        ReportRequest(
            date(2026, 10, 1), date(2026, 10, 31), series="HST"
        ),
    )

    assert (
        "set_text_anywhere",
        {"title": "Series"},
        "HST",
    ) in session.calls
    assert (
        "set_text_anywhere",
        {"title": "From"},
        "01-10-2026",
    ) in session.calls
    assert (
        "set_text_anywhere",
        {"title": "To"},
        "31-10-2026",
    ) in session.calls


def test_exporter_export_flow_handles_the_open_file_prompt(
    tmp_path: Path,
) -> None:
    target = tmp_path / "sales.xlsx"
    profile = BusyUiProfile()
    profile.export.format_keys = "{TAB}"
    profile.export.file_stable_sec = 0.0
    profile.export.file_ready_timeout_sec = 1.0
    session = ExportFakeSession(target)
    exporter = BusyExporter(profile, sleep=lambda _: None)

    result = exporter.export(session, target)

    assert result == target
    assert target.is_file()
    assert ("send_keys", "n", session.open_dialog) in session.calls
    assert (
        "send_keys",
        "{ENTER}",
        session.success_dialog,
    ) in session.calls
    assert ("set_control_text", session._children[0], str(target)) in session.calls


def test_exporter_uses_an_explicit_path_control(tmp_path: Path) -> None:
    target = tmp_path / "sales.xlsx"
    profile = BusyUiProfile()
    profile.export.format_keys = "{TAB}"
    profile.export.path_control = {"class_name": "Edit", "control_id": 7}
    profile.export.auto_detect_path_control = False
    profile.export.auto_detect_open_after_control = False
    profile.export.file_stable_sec = 0.0
    profile.export.file_ready_timeout_sec = 1.0
    session = ExportFakeSession(target)
    exporter = BusyExporter(profile, sleep=lambda _: None)

    exporter.export(session, target)

    assert (
        "set_text",
        session.export_dialog,
        profile.export.path_control,
        str(target),
    ) in session.calls


def test_exporter_refuses_an_uncalibrated_format(tmp_path: Path) -> None:
    target = tmp_path / "sales.xlsx"
    profile = BusyUiProfile()
    profile.export.auto_detect_path_control = False
    profile.export.auto_detect_open_after_control = False
    session = ExportFakeSession(target)

    with pytest.raises(BusyExportError, match="Data Format"):
        BusyExporter(profile).export(session, target)


def test_exporter_uses_a_calibrated_format_combo(tmp_path: Path) -> None:
    target = tmp_path / "sales.xlsx"
    profile = BusyUiProfile()
    profile.export.format_control = {"class_name": "ComboBox", "control_id": 5}
    profile.export.format_value = "Microsoft Excel"
    profile.export.file_stable_sec = 0.0
    profile.export.file_ready_timeout_sec = 1.0
    session = ExportFakeSession(target)

    result = BusyExporter(profile, sleep=lambda _: None).export(session, target)

    assert result == target
    assert (
        "select_combo_item",
        profile.export.format_control,
        "Microsoft Excel",
    ) in session.calls
    assert not any(
        call[0] == "send_keys" and call[1] == profile.export.format_keys
        for call in session.calls
    )


def test_exporter_polls_the_busy_appended_extension_candidates(
    tmp_path: Path,
) -> None:
    profile = BusyUiProfile()
    profile.export.append_extension = True
    exporter = BusyExporter(profile)
    target = tmp_path / "sales.xlsx"

    candidates = exporter._candidate_paths(exporter._entry_path(target))

    assert candidates[0] == target
    assert (tmp_path / "sales") in candidates
    assert (tmp_path / "sales.xlsm") in candidates
    assert (tmp_path / "sales.xls") in candidates
    assert exporter._entry_path(target) == tmp_path / "sales"


def test_exporter_prefers_the_xlsx_candidate_over_an_extensionless_file(
    tmp_path: Path,
) -> None:
    target = tmp_path / "sales.xlsx"
    make_workbook(target)
    extensionless = target.with_suffix("")
    make_workbook(extensionless)
    profile = BusyUiProfile()
    profile.export.append_extension = True
    profile.export.file_stable_sec = 0.0
    exporter = BusyExporter(profile, sleep=lambda _: None)

    result = exporter._wait_for_file(
        FakeSession(),
        FakeDialog("Export"),
        exporter._candidate_paths(exporter._entry_path(target)),
    )

    assert result == target


def test_exporter_enters_the_extensionless_name_for_a_busy_export(
    tmp_path: Path,
) -> None:
    target = tmp_path / "sales.xlsx"
    profile = BusyUiProfile()
    profile.export.append_extension = True
    profile.export.format_keys = "{TAB}"
    profile.export.file_stable_sec = 0.0
    profile.export.file_ready_timeout_sec = 1.0
    session = ExportFakeSession(target)

    result = BusyExporter(profile, sleep=lambda _: None).export(session, target)

    assert result == target
    assert (
        "set_control_text",
        session._children[0],
        str(tmp_path / "sales"),
    ) in session.calls


def test_exporter_refuses_an_uncalibrated_path(tmp_path: Path) -> None:
    target = tmp_path / "sales.xlsx"
    profile = BusyUiProfile()
    profile.export.format_keys = "{TAB}"
    profile.export.auto_detect_path_control = False
    profile.export.auto_detect_open_after_control = False
    session = ExportFakeSession(target)
    session._children = []

    with pytest.raises(BusyExportError, match="not calibrated"):
        BusyExporter(profile).export(session, target)


def test_exporter_ignores_the_export_dialog_after_confirming() -> None:
    exporter = BusyExporter(BusyUiProfile())
    session = FakeSession()
    export_dialog = FakeDialog("Export Sales Register")
    session._dialogs = [export_dialog]

    exporter._handle_post_export_dialogs(session, export_dialog, set())

    assert not any(call[0] == "send_keys" for call in session.calls)


def test_exporter_stops_on_an_unexpected_dialog() -> None:
    exporter = BusyExporter(BusyUiProfile())
    session = FakeSession()
    session._dialogs = [FakeDialog("Printer not ready")]

    with pytest.raises(BusyUnsafeStateError, match="Unexpected"):
        exporter._handle_post_export_dialogs(
            session, FakeDialog("Export"), set()
        )


def test_exporter_stops_on_a_save_changes_dialog() -> None:
    exporter = BusyExporter(BusyUiProfile())
    session = FakeSession()
    session._dialogs = [FakeDialog("Save changes?")]

    with pytest.raises(BusyUnsafeStateError, match="discard"):
        exporter._handle_post_export_dialogs(
            session, FakeDialog("Export"), set()
        )


def test_exporter_stops_on_an_exit_dialog() -> None:
    exporter = BusyExporter(BusyUiProfile())
    session = FakeSession()
    session._dialogs = [FakeDialog("Are you sure you want to quit?")]

    with pytest.raises(BusyUnsafeStateError, match="exit"):
        exporter._handle_post_export_dialogs(
            session, FakeDialog("Export"), set()
        )


def test_exporter_rejects_a_non_excel_file(tmp_path: Path) -> None:
    path = tmp_path / "bad.xlsx"
    path.write_text("not an excel file", encoding="utf-8")

    with pytest.raises(BusyExportError):
        BusyExporter(BusyUiProfile())._validate_workbook(path)


def test_exporter_accepts_an_extensionless_xlsx_export(tmp_path: Path) -> None:
    path = tmp_path / "sales.xlsx"
    make_workbook(path)
    extensionless = path.with_suffix("")
    path.rename(extensionless)

    BusyExporter(BusyUiProfile())._validate_workbook(extensionless)


def test_exporter_times_out_when_no_file_appears(tmp_path: Path) -> None:
    profile = BusyUiProfile()
    profile.export.file_ready_timeout_sec = 0.05
    profile.export.file_stable_sec = 0.0
    exporter = BusyExporter(profile, sleep=lambda _: None)

    with pytest.raises(BusyExportError, match="did not create"):
        exporter._wait_for_file(
            FakeSession(), FakeDialog("Export"), (tmp_path / "missing.xlsx",)
        )


def test_pipeline_imports_and_leaves_no_temp_file(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    session = FakeSession()
    exporter = FakeExporter()
    recipe = FakeRecipe()
    importer = FakeImporter(delete=True)
    idle_calls: list[tuple[float, float]] = []

    def idle_waiter(min_idle: float, *, timeout: float) -> None:
        idle_calls.append((min_idle, timeout))

    pipeline = BusyAutomationPipeline(
        config,
        importer,
        session_factory=lambda profile: session,
        exporter=exporter,
        recipe=recipe,
        idle_waiter=idle_waiter,
    )

    result = pipeline.run(
        BusyAutomationRequest(
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 31),
        )
    )

    assert result.rows_found == 2
    assert result.rows_imported == 2
    assert result.deleted is True
    assert not list(config.temp_dir.glob("*.xlsx"))
    assert importer.calls[0][1] == "bills"
    assert recipe.requests[0].start_date == date(2026, 10, 1)
    assert idle_calls == [(0.0, 1.0)]
    assert session.calls[0] == ("ensure_main_menu",)
    assert session.calls[-1] == ("close",)


def test_pipeline_safety_net_deletes_when_the_parser_does_not(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    exporter = FakeExporter()
    pipeline = BusyAutomationPipeline(
        config,
        FakeImporter(delete=False),
        session_factory=lambda profile: FakeSession(),
        exporter=exporter,
        recipe=FakeRecipe(),
        idle_waiter=lambda *args, **kwargs: None,
    )

    result = pipeline.run(
        BusyAutomationRequest(
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 31),
        )
    )

    assert result.deleted is True
    assert exporter.last_target is not None
    assert not exporter.last_target.exists()


def test_pipeline_deletes_the_temp_file_when_importing_fails(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    exporter = FakeExporter()
    pipeline = BusyAutomationPipeline(
        config,
        FakeImporter(fail=True),
        session_factory=lambda profile: FakeSession(),
        exporter=exporter,
        recipe=FakeRecipe(),
        idle_waiter=lambda *args, **kwargs: None,
    )

    with pytest.raises(RuntimeError, match="parse failed"):
        pipeline.run(
            BusyAutomationRequest(
                start_date=date(2026, 10, 1),
                end_date=date(2026, 10, 31),
            )
        )

    assert exporter.last_target is not None
    assert not exporter.last_target.exists()


def test_recipe_for_category_routes_account_ledger_profiles() -> None:
    profile = BusyUiProfile()

    bills = recipe_for_category(profile, "bills")
    credit_notes = recipe_for_category(profile, "credit_notes")
    debit_notes = recipe_for_category(profile, "debit_notes")

    assert isinstance(bills, AccountLedgerSalesRecipe)
    assert isinstance(credit_notes, AccountLedgerSalesReturnRecipe)
    assert isinstance(debit_notes, PurchaseReturnRecipe)
    assert bills.profile.account_name == "Sales"
    assert credit_notes.profile.account_name == "Sales Return"
    assert debit_notes.profile.account_name == "Purchase Return"
    assert bills.profile.format_name == "BAGS"
    assert bills.profile.optional_fields_value is True
    assert bills.profile.bill_references_value is True
    assert bills.profile.calibrated is False

    with pytest.raises(BusyAutomationError, match="Unknown"):
        recipe_for_category(profile, "expenses")


def test_pipeline_rejects_a_recipe_for_the_wrong_category(
    tmp_path: Path,
) -> None:
    pipeline = BusyAutomationPipeline(
        make_config(tmp_path),
        FakeImporter(),
        session_factory=lambda profile: FakeSession(),
        exporter=FakeExporter(),
        recipe=FakeRecipe(),
        idle_waiter=lambda *args, **kwargs: None,
    )

    with pytest.raises(BusyAutomationError, match="cannot export"):
        pipeline.run(
            BusyAutomationRequest(
                start_date=date(2026, 10, 1),
                end_date=date(2026, 10, 31),
                category="credit_notes",
            )
        )


def test_pipeline_passes_the_requested_category_to_the_importer(
    tmp_path: Path,
) -> None:
    class CategoryRecipe(FakeRecipe):
        def __init__(self, category: str) -> None:
            super().__init__()
            self.category = category

    importer = FakeImporter()
    pipeline = BusyAutomationPipeline(
        make_config(tmp_path),
        importer,
        session_factory=lambda profile: FakeSession(),
        exporter=FakeExporter(),
        recipe=CategoryRecipe("debit_notes"),
        idle_waiter=lambda *args, **kwargs: None,
    )

    result = pipeline.run(
        BusyAutomationRequest(
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 31),
            category="debit_notes",
        )
    )

    assert result.category == "debit_notes"
    assert importer.calls[0][1] == "debit_notes"


def test_pipeline_rejects_a_reversed_date_range(tmp_path: Path) -> None:
    pipeline = BusyAutomationPipeline(
        make_config(tmp_path),
        FakeImporter(),
        session_factory=lambda profile: FakeSession(),
        exporter=FakeExporter(),
        recipe=FakeRecipe(),
        idle_waiter=lambda *args, **kwargs: None,
    )

    with pytest.raises(ValueError, match="start date"):
        pipeline.run(
            BusyAutomationRequest(
                start_date=date(2026, 10, 31),
                end_date=date(2026, 10, 1),
            )
        )


def test_busy_lock_can_be_reacquired_after_release(tmp_path: Path) -> None:
    lock_path = tmp_path / "busy.lock"

    with acquire_busy_lock(lock_path, 0.2):
        assert lock_path.exists()

    with acquire_busy_lock(lock_path, 0.2):
        pass


def test_busy_lock_times_out_when_another_job_holds_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lock_module, "_try_lock", lambda fd: False)

    with pytest.raises(BusyLockTimeoutError):
        with acquire_busy_lock(tmp_path / "busy.lock", 0.05):
            pass


def test_wait_for_user_idle_waits_until_the_desktop_is_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lock_module.sys, "platform", "win32")
    idle_values = iter([0.0, 2.0])
    monkeypatch.setattr(
        lock_module, "_windows_idle_seconds", lambda: next(idle_values)
    )
    monkeypatch.setattr(lock_module.time, "sleep", lambda _: None)

    wait_for_user_idle(1.0, timeout=1.0)


def test_wait_for_user_idle_fails_when_the_user_keeps_working(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lock_module.sys, "platform", "win32")
    monkeypatch.setattr(lock_module, "_windows_idle_seconds", lambda: 0.0)

    with pytest.raises(BusyUserActiveError):
        wait_for_user_idle(1.0, timeout=0.0)


