"""Manual-only execution, Excel boundaries, A:G preservation and uncertain writes."""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from app.config import Settings
from app.db import Database
from app.domains.pouncha_sync.busy import FLAGS, BusyExporter
from app.domains.pouncha_sync.parser import Sale, SyncError, bill_key, parse_sales
from app.domains.pouncha_sync.repository import RunRepository
from app.domains.pouncha_sync.service import PounchaService
from app.domains.pouncha_sync.sheets import HEADERS, GoogleSheet, Snapshot, compare, snapshot
from app.main import create_app
from fastapi.testclient import TestClient
from openpyxl import Workbook

from tests.fakes import FakeBridge

START = date(2026, 11, 1)
END = date(2026, 11, 5)


def export_bytes(
    *,
    no_challan: bool = False,
    extra: int = 0,
    company: str = "H.S. TRADERS",
    account: str = "Sales",
) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append([company])
    sheet.append(["Account Ledger"])
    sheet.append([f"Account : {account}"])
    for _ in range(extra):
        sheet.append([])
    sheet.append(["Date", "Type", "Vch/Bill No", "Account", "Debit(Rs.)", "Credit(Rs.)"])
    sheet.append([START, "Sale", "HST/26-27/1191", "Party One", 0, 100])
    if not no_challan:
        sheet.append([None, None, None, "HS-1182", 0, 0])
    for _ in range(12):
        sheet.append([None, None, None, "Unrelated narration", 0, 0])
    sheet.append([None, None, None, "Transport : TEMPU AJAY", 0, 0])
    sheet.append([None, None, None, "Vehicle No. : PB07AE4179", 0, 0])
    sheet.append([None, None, None, "Station : AMRITSAR", 0, 0])
    sheet.append([None, None, None, "E-Way Bill No. : 1234", 0, 0])
    sheet.append([date(2026, 11, 2), "Sale", "HST/L/26-27/78", "Party Two", 0, 200])
    sheet.append([None, None, None, "Hsl-78", 0, 0])
    sheet.append([None, None, None, "Transport : A-LOCAL", 0, 0])
    sheet.append([None, None, None, "Total", 0, 300])
    sheet.append([None, None, None, "Transport : MUST NOT LEAK"])
    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def parse(tmp_path: Path, **kwargs: Any) -> list[Sale]:
    path = tmp_path / "sample.xlsx"
    path.write_bytes(export_bytes(**kwargs))
    return parse_sales(path, "H.S. TRADERS", START, END)


class FakeSheet:
    def __init__(self) -> None:
        self.rows = [
            HEADERS + [""],
            ["31/10/2026", "HST/26-27/1182", "Old Party", "", "", "", "HS-1180", "P"],
        ]
        self.reads = 0
        self.writes = 0
        self.lose_response = False
        self.fail_before_commit = False
        self.corrupt_old = False

    def read(self) -> Snapshot:
        self.reads += 1
        return snapshot([list(row) for row in self.rows])

    def append(self, records: list[Sale], before: Snapshot) -> str:
        self.writes += 1
        if self.fail_before_commit:
            raise SyncError("Connection lost before a response.")
        start = len(self.rows) + 1
        self.rows.extend(record.cells() for record in records)
        if self.corrupt_old:
            self.rows[1][7] = "Changed by another editor"
        if self.lose_response:
            raise SyncError("Connection lost after commit.")
        return f"'POUNCHA 26-27'!A{start}:G{len(self.rows)}"


class FakeExporter:
    calls = 0

    def export(self, start: date, end: date, directory: Path) -> Path:
        self.calls += 1
        path = directory / "sales.xlsx"
        path.write_bytes(export_bytes())
        return path


def make_service(tmp_path: Path) -> tuple[PounchaService, FakeSheet, FakeExporter]:
    settings = Settings(database_path=tmp_path / "manual.sqlite3")
    database = Database(settings.database_path)
    database.initialize()
    repository = RunRepository(database)
    sheet, exporter = FakeSheet(), FakeExporter()
    return PounchaService(settings, repository, sheet, exporter), sheet, exporter


def test_parser_uses_labels_and_stops_at_voucher_and_footer(tmp_path: Path) -> None:
    records = parse(tmp_path, extra=10)
    assert len(records) == 2
    assert records[0].challan == "HS-1182"
    assert records[0].transport == "TEMPU AJAY"
    assert records[0].vehicle == "PB07AE4179"
    assert records[1].transport == "A-LOCAL"
    assert records[1].challan == "Hsl-78"
    assert records[1].vehicle == ""
    assert records[0].cells()[0] == "01/11/2026"


def test_missing_challan_never_uses_transport(tmp_path: Path) -> None:
    records = parse(tmp_path, no_challan=True)
    assert records[0].challan == ""
    assert records[0].transport == "TEMPU AJAY"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"company": "Other Company"},
        {"company": "H.S. TRADERS PVT LTD"},
        {"account": "Sales Return"},
    ],
)
def test_wrong_export_rejected(tmp_path: Path, kwargs: dict[str, Any]) -> None:
    with pytest.raises(SyncError):
        parse(tmp_path, **kwargs)


def test_out_of_range_export_rejected(tmp_path: Path) -> None:
    path = tmp_path / "sample.xlsx"
    path.write_bytes(export_bytes())
    with pytest.raises(SyncError, match="outside"):
        parse_sales(path, "H.S. TRADERS", date(2026, 11, 2), END)


def test_full_voucher_identity_and_strict_headers() -> None:
    assert bill_key(" hst / L / 26-27 / 078 ") == "HST/L/26-27/78"
    assert bill_key("HST/26-27/78") != bill_key("HST/L/26-27/78")
    with pytest.raises(SyncError, match="headers"):
        snapshot([["Wrong"]])
    with pytest.raises(SyncError, match="Duplicate"):
        snapshot([HEADERS, ["01/11/2026", "HST/26-27/1", "A"], ["01-11-2026", "HST/26-27/1", "A"]])


def test_preview_and_status_never_write_or_start_export_automatically(tmp_path: Path) -> None:
    instance, sheet, exporter = make_service(tmp_path)
    instance.repository.recover()
    state = instance.status()
    assert state["scheduler_enabled"] is False
    assert state["manual_only"] is True
    assert exporter.calls == sheet.writes == 0
    run = instance.queue(START, END, True, "upload")
    assert exporter.calls == sheet.writes == 0
    instance.execute(run["run_id"], export_bytes(no_challan=True))
    result = instance.repository.get(run["run_id"])
    assert result and result["status"] == "success" and result["new_count"] == 2
    assert result["preview"][0][6] == ""
    assert sheet.writes == exporter.calls == 0


def test_manual_sync_append_verify_repeat_skips_and_preserves_remarks(tmp_path: Path) -> None:
    instance, sheet, exporter = make_service(tmp_path)
    original = [list(row) for row in sheet.rows]
    run = instance.queue(None, END, False, "busy")
    instance.execute(run["run_id"])
    saved = instance.repository.get(run["run_id"])
    assert saved and saved["status"] == "success" and saved["appended_count"] == 2
    assert saved["start_date"] == "2026-10-31"
    assert sheet.rows[:2] == original
    assert exporter.calls == sheet.writes == 1
    second = instance.queue(START, END, False, "upload")
    instance.execute(second["run_id"], export_bytes())
    saved = instance.repository.get(second["run_id"])
    assert saved and saved["appended_count"] == 0 and saved["existing_count"] == 2
    assert sheet.writes == 1


def test_only_one_active_run_and_unknown_write_is_never_replayed(tmp_path: Path) -> None:
    instance, sheet, _ = make_service(tmp_path)
    sheet.lose_response = True
    run = instance.queue(START, END, False, "upload")
    with pytest.raises(SyncError, match="active"):
        instance.queue(START, END, False, "upload")
    instance.execute(run["run_id"], export_bytes())
    saved = instance.repository.get(run["run_id"])
    assert saved and saved["status"] == "needs_review"
    instance.execute(run["run_id"], export_bytes())
    assert sheet.writes == 1
    with pytest.raises(SyncError, match="review"):
        instance.queue(START, END, False, "upload")
    resolved = instance.reconcile(run["run_id"])
    assert resolved["status"] == "success" and resolved["appended_count"] == 2
    assert sheet.writes == 1


def test_failed_verification_blocks_until_explicit_review(tmp_path: Path) -> None:
    instance, sheet, _ = make_service(tmp_path)
    sheet.fail_before_commit = True
    run = instance.queue(START, END, False, "upload")
    instance.execute(run["run_id"], export_bytes())
    with pytest.raises(SyncError, match="missing"):
        instance.reconcile(run["run_id"])
    instance.release(run["run_id"])
    assert sheet.writes == 1
    assert instance.repository.get(run["run_id"])["status"] == "reviewed"


def test_changes_to_existing_remarks_are_reported_as_uncertain(tmp_path: Path) -> None:
    instance, sheet, _ = make_service(tmp_path)
    sheet.corrupt_old = True
    run = instance.queue(START, END, False, "upload")
    instance.execute(run["run_id"], export_bytes())
    result = instance.repository.get(run["run_id"])
    assert result and result["status"] == "needs_review"
    assert "Existing rows changed" in result["error"]
    assert sheet.writes == 1


def test_invalid_dates_do_not_create_runs(tmp_path: Path) -> None:
    instance, sheet, exporter = make_service(tmp_path)
    with pytest.raises(SyncError, match="Start date"):
        instance.queue(END, START, False, "busy")
    assert instance.repository.recent() == []
    assert sheet.reads == sheet.writes == exporter.calls == 0


@pytest.mark.parametrize("stage,expected", [("exporting", "failed"), ("appending", "needs_review")])
def test_restart_never_resumes_a_run(tmp_path: Path, stage: str, expected: str) -> None:
    instance, sheet, exporter = make_service(tmp_path)
    run = instance.queue(START, END, False, "busy")
    instance.repository.update(run["run_id"], status="running", stage=stage)
    instance.repository.recover()
    assert instance.repository.get(run["run_id"])["status"] == expected
    assert sheet.writes == exporter.calls == 0


def test_existing_changed_bill_is_preserved(tmp_path: Path) -> None:
    record = parse(tmp_path)[0]
    old = record.cells()
    old[3] = "Original transport"
    new, conflicts, count = compare([record], snapshot([HEADERS, old]))
    assert not new and conflicts == [record.bill] and count == 1


def test_http_reads_and_page_reload_do_not_queue_sync(tmp_path: Path) -> None:
    settings = Settings(database_path=tmp_path / "api.sqlite3")
    app = create_app(settings, FakeBridge(), start_worker=False)
    sheet, exporter = FakeSheet(), FakeExporter()
    with TestClient(app) as client:
        app.state.pouncha_service.sheet = sheet
        app.state.pouncha_service.exporter = exporter
        for _ in range(2):
            assert client.get("/api/pouncha-sync/status").json()["recent_runs"] == []
        assert sheet.writes == exporter.calls == 0
        assert not hasattr(app.state, "pouncha_scheduler")
        denied = client.post(
            "/api/pouncha-sync/run",
            json={"end_date": END.isoformat()},
            headers={"Origin": "https://unexpected.example"},
        )
        assert denied.status_code == 403
        response = client.post(
            "/api/pouncha-sync/upload",
            data={
                "start_date": START.isoformat(),
                "end_date": END.isoformat(),
                "preview_only": "true",
            },
            files={"file": ("sales.xlsx", export_bytes(), "application/octet-stream")},
        )
        assert response.status_code == 202
        result = client.get("/api/pouncha-sync/runs/" + response.json()["run_id"]).json()
        assert result["status"] == "success" and result["new_count"] == 2
        assert "intended_rows" not in result
        assert sheet.writes == exporter.calls == 0


def test_google_append_is_literal_and_seven_columns_only(monkeypatch: pytest.MonkeyPatch) -> None:
    client = GoogleSheet(Settings())
    sheet = FakeSheet().read()
    captured = {}

    def request(method: str, suffix: str, **kwargs: Any) -> dict[str, Any]:
        captured.update(method=method, suffix=suffix, **kwargs)
        return {"updates": {"updatedRange": "'POUNCHA 26-27'!A3:G3", "updatedRows": 1}}

    monkeypatch.setattr(client, "_request", request)
    client.append([Sale(START, "HST/26-27/1191", "=FORMULA()")], sheet)
    assert captured["params"] == {"valueInputOption": "RAW", "insertDataOption": "OVERWRITE"}
    assert len(captured["json"]["values"][0]) == 7
    assert "G2" in captured["suffix"]
    assert ":append" in captured["suffix"]


def test_close_company_uses_no_and_unknown_dialog_is_not_answered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exporter = BusyExporter(Settings(database_path=tmp_path / "unused.sqlite3"))
    clicks = []

    class Dialog:
        def window_text(self) -> str:
            return "Close Company !!"

    monkeypatch.setattr(exporter, "_guard", lambda *_: [Dialog()])
    monkeypatch.setattr(exporter, "_click", lambda root, name: clicks.append(name))
    exporter._home(object(), object())
    assert clicks == ["No"]
    assert FLAGS == ["Y", "Y", "Y", "N", "N", "N", "N", "N", "Y"]

    class Blocked:
        def is_enabled(self) -> bool:
            return False

        def type_keys(self, *_: Any, **__: Any) -> None:
            raise AssertionError("No guessed keystrokes may reach a blocked window")

    monkeypatch.setattr(exporter, "_guard", lambda *_: [])
    with pytest.raises(SyncError, match="blocked"):
        exporter._home(Blocked(), object())


def test_vb6_enabled_owned_form_is_selected_under_disabled_company_window() -> None:
    class Form:
        def __init__(self, handle: int, enabled: bool, children: list[Any]) -> None:
            self.handle = handle
            self.enabled = enabled
            self.children = children

        def process_id(self) -> int:
            return 123

        def is_visible(self) -> bool:
            return True

        def is_enabled(self) -> bool:
            return self.enabled

        def descendants(self, **kwargs: Any) -> list[Any]:
            return self.children

    active = Form(3, True, [])
    options = Form(2, False, [active])
    main = Form(1, False, [options, active])

    class Desktop:
        def windows(self, **kwargs: Any) -> list[Any]:
            return [main]

    assert BusyExporter._active_window(main, Desktop()) is active
    active.enabled = False
    with pytest.raises(SyncError, match="blocked"):
        BusyExporter._active_window(main, Desktop())


def test_escape_targets_owned_report_options_not_disabled_company(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exporter = BusyExporter(Settings())
    keys = []
    clicks = []

    class Company:
        handle = 1

        def type_keys(self, *_: Any, **__: Any) -> None:
            raise AssertionError("Disabled owner must not receive keystrokes")

    class Options:
        handle = 2

        def window_text(self) -> str:
            return "Report Options !"

        def type_keys(self, value: str, **kwargs: Any) -> None:
            keys.append(value)

    class CloseCompany:
        def window_text(self) -> str:
            return "Close Company !!"

    observations = iter([[Options()], [CloseCompany()]])
    monkeypatch.setattr(exporter, "_guard", lambda *_: next(observations))
    monkeypatch.setattr(exporter, "_click", lambda root, label: clicks.append(label))
    monkeypatch.setattr(exporter, "_is_report", lambda *_: False)
    exporter._home(Company(), object())
    assert keys == ["{ESC}"]
    assert clicks == ["No"]


def test_other_busy_screens_get_at_most_fifteen_escapes(monkeypatch: pytest.MonkeyPatch) -> None:
    exporter = BusyExporter(Settings())
    keys = []

    class Window:
        handle = 2

        def window_text(self) -> str:
            return "Unexpected input dialog"

        def type_keys(self, key: str, **kwargs: Any) -> None:
            keys.append(key)

    class Company:
        handle = 1

    monkeypatch.setattr(exporter, "_guard", lambda *_: [Window()])
    monkeypatch.setattr("app.domains.pouncha_sync.busy.time.sleep", lambda *_: None)
    assert exporter._home(Company(), object()) is False
    assert keys == ["{ESC}"] * 15


@pytest.mark.parametrize("valid_layout", [True, False])
def test_direct_alt_l_once_after_escape_limit(
    monkeypatch: pytest.MonkeyPatch,
    valid_layout: bool,
) -> None:
    exporter = BusyExporter(Settings())
    keys = []

    class Window:
        def window_text(self) -> str:
            return "Another BUSY screen"

        def type_keys(self, key: str, **kwargs: Any) -> None:
            keys.append(key)

    class Edit:
        def __init__(self, value: str) -> None:
            self.value = value

        def get_value(self) -> str:
            return self.value

    window = Window()
    edits = [
        Edit(value)
        for value in [
            "STANDARD",
            "Sales",
            "31-10-2026",
            "04-11-2026",
            "Single Account (Auto)",
            "Name",
            *FLAGS,
        ]
    ]
    if not valid_layout:
        edits[2].value = "Not a date field"
    monkeypatch.setattr(exporter, "_guard", lambda *_: [window])
    monkeypatch.setattr(exporter, "_edits", lambda *_: edits)
    monkeypatch.setattr(exporter, "_buttons", lambda *_: [object()])
    monkeypatch.setattr("app.domains.pouncha_sync.busy.time.sleep", lambda *_: None)
    clock = iter([0.0, 0.0, 20.0])
    monkeypatch.setattr("app.domains.pouncha_sync.busy.time.monotonic", lambda: next(clock))
    if valid_layout:
        assert exporter._open_ledger(object(), object()) == (window, edits)
    else:
        with pytest.raises(SyncError, match="15 Escape presses.*one direct Alt"):
            exporter._open_ledger(object(), object())
    assert keys == ["{ESC}"] * 15 + ["%l"]


def test_close_company_reached_on_final_escape_is_answered_no(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exporter = BusyExporter(Settings())
    keys, clicks = [], []

    class Window:
        def window_text(self) -> str:
            return "Close Company !!" if len(keys) == 15 else "Another BUSY screen"

        def type_keys(self, key: str, **kwargs: Any) -> None:
            keys.append(key)

    monkeypatch.setattr(exporter, "_guard", lambda *_: [Window()])
    monkeypatch.setattr(exporter, "_click", lambda window, name: clicks.append(name))
    monkeypatch.setattr("app.domains.pouncha_sync.busy.time.sleep", lambda *_: None)
    assert exporter._home(object(), object()) is True
    assert keys == ["{ESC}"] * 15
    assert clicks == ["No"]


def test_unsaved_prompt_still_prevents_escapes_and_alt_l(monkeypatch: pytest.MonkeyPatch) -> None:
    exporter = BusyExporter(Settings())

    class UnsafePrompt:
        def window_text(self) -> str:
            return "Discard unsaved voucher changes?"

        def type_keys(self, *_: Any, **__: Any) -> None:
            raise AssertionError("No keys may be sent to an unsafe confirmation")

    monkeypatch.setattr(exporter, "_active_window", lambda *_: UnsafePrompt())
    monkeypatch.setattr(exporter, "_visible", lambda *_: [])
    with pytest.raises(SyncError, match="unsaved-work"):
        exporter._open_ledger(object(), object())


def test_offscreen_vb6_helper_controls_are_excluded() -> None:
    from types import SimpleNamespace

    class Control:
        def __init__(self, left: int, top: int) -> None:
            self.left, self.top = left, top

        def is_visible(self) -> bool:
            return True

        def is_enabled(self) -> bool:
            return True

        def rectangle(self) -> Any:
            return SimpleNamespace(
                left=self.left, right=self.left + 20, top=self.top, bottom=self.top + 20
            )

    onscreen, hidden_helper = Control(100, 100), Control(-1600, 1700)

    class Form:
        def rectangle(self) -> Any:
            return SimpleNamespace(left=0, right=1000, top=0, bottom=700)

        def descendants(self, **kwargs: Any) -> list[Any]:
            return [onscreen, hidden_helper]

    assert BusyExporter._visible(Form(), "Edit") == [onscreen]
