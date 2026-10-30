"""Pouncha parser, deduplication, scheduler, service and API tests."""

from __future__ import annotations

import asyncio
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from app.api.routes import pouncha_sync as pouncha_routes
from app.config import Settings
from app.db import Database
from app.domains.busy_automation.errors import BusyNotRunningError
from app.domains.busy_automation.lock import acquire_busy_lock
from app.domains.pouncha_sync.models import (
    ParsedPounchaWorkbook,
    PounchaSaleRecord,
    PounchaTrigger,
)
from app.domains.pouncha_sync.parser import (
    OUTPUT_HEADERS,
    PounchaParseError,
    parse_pouncha_sales_workbook,
    voucher_identity,
    write_pouncha_archive,
)
from app.domains.pouncha_sync.repository import PounchaSyncRepository
from app.domains.pouncha_sync.scheduler import (
    PounchaSyncScheduler,
    next_midnight_after,
    should_catch_up,
    start_of_today,
)
from app.domains.pouncha_sync.service import (
    PounchaSyncService,
    create_pouncha_sync_service,
)
from app.domains.pouncha_sync.sheets_client import (
    GoogleSheetsClient,
    PounchaSheetError,
    rows_for_records,
    select_new_records,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=IST)
HEADER = ["Date", "Type", "Vch/Bill No", "Account", "Debit", "Credit"]
PREAMBLE = [
    ["H.S. TRADERS"],
    ["Account Ledger"],
    ["01-10-2026 to 31-10-2026"],
    [],
]


def write_ledger(
    path: Path,
    rows: list[list[Any]],
    *,
    sheet_title: str = "Account Ledger",
) -> Path:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet_title
    for row in rows:
        worksheet.append(row)
    workbook.save(path)
    return path


def standard_rows() -> list[list[Any]]:
    return [
        *PREAMBLE,
        HEADER,
        [date(2026, 10, 25), "Sale", "HST/26-27/1163", "ABC TEXTILES", 1000, 0],
        [None, None, None, "1163  0  0  0"],
        [None, None, None, "TRANSPORT : ROAD"],
        [None, None, None, "VEHICLE NO. : PB10AB1234"],
        [None, None, None, "STATION : Ludhiana"],
        [date(2026, 10, 26), "Purchase", "PUR/26-27/9", "SUPPLIER", 0, 500],
        [date(2026, 10, 27), "Sale", "HST/L/26-27/42", "XYZ TRADERS", 500, 0],
        [None, None, None, "TRANSPORT : COURIER"],
        [None, None, None, "TOTAL"],
    ]


def parsed_workbook(*records: PounchaSaleRecord) -> ParsedPounchaWorkbook:
    return ParsedPounchaWorkbook(
        records=tuple(records), warnings=(), sheet_name="Account Ledger"
    )


class FakeSheets:
    def __init__(self, existing: set[str] | None = None) -> None:
        self.existing = set(existing or ())
        self.appended: list[list[str]] = []
        self._configured = True

    @property
    def configured(self) -> bool:
        return self._configured

    def existing_voucher_keys(self) -> set[str]:
        return set(self.existing)

    def append_rows(self, rows: list[list[str]]) -> int:
        self.appended.extend(rows)
        return len(rows)


class FakeWorksheet:
    def __init__(self, values: list[str]) -> None:
        self.values = values
        self.appended: list[list[str]] = []

    def col_values(self, column: int) -> list[str]:
        assert column == 2
        return list(self.values)

    def append_rows(self, rows: list[list[str]], *, value_input_option: str) -> None:
        assert value_input_option == "USER_ENTERED"
        self.appended.extend(rows)


class FakeExporter:
    def __init__(
        self,
        parsed: ParsedPounchaWorkbook | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.parsed = parsed or parsed_workbook()
        self.error = error
        self.calls: list[tuple[date, date]] = []

    def export_sales(
        self, start_date: date, end_date: date
    ) -> ParsedPounchaWorkbook:
        self.calls.append((start_date, end_date))
        if self.error is not None:
            raise self.error
        return self.parsed


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_path": tmp_path / "pouncha.sqlite3",
        "pouncha_upload_dir": tmp_path / "uploads",
        "pouncha_lock_path": tmp_path / "pouncha.lock",
        "busy_lock_path": tmp_path / "busy.lock",
        "pouncha_local_excel_path": None,
        "pouncha_sync_enabled": True,
        "busy_automation_timeout_seconds": 1.0,
    }
    values.update(overrides)
    return Settings(**values)


def make_repository(tmp_path: Path) -> PounchaSyncRepository:
    database = Database(tmp_path / "pouncha.sqlite3")
    database.initialize()
    return PounchaSyncRepository(database)


def make_service(
    tmp_path: Path,
    *,
    exporter: FakeExporter | None = None,
    sheets: FakeSheets | None = None,
    busy_available: bool = True,
    **settings_overrides: Any,
) -> PounchaSyncService:
    return PounchaSyncService(
        settings=make_settings(tmp_path, **settings_overrides),
        repository=make_repository(tmp_path),
        sheets_client=sheets or FakeSheets(),
        exporter=exporter or FakeExporter(),
        busy_available=lambda: busy_available,
        now=lambda: NOW,
    )


def test_parser_reads_sale_rows_with_details(tmp_path: Path) -> None:
    path = write_ledger(tmp_path / "ledger.xlsx", standard_rows())

    parsed = parse_pouncha_sales_workbook(path)

    assert parsed.sheet_name == "Account Ledger"
    assert len(parsed.records) == 2
    first = parsed.records[0]
    assert first.date == date(2026, 10, 25)
    assert first.date_text == "25/10/2026"
    assert first.voucher_no == "HST/26-27/1163"
    assert first.account == "ABC TEXTILES"
    assert first.order_no == "1163"
    assert first.transport == "ROAD"
    assert first.vehicle_no == "PB10AB1234"
    assert first.station == "LUDHIANA"
    second = parsed.records[1]
    assert second.voucher_no == "HST/L/26-27/42"
    assert second.order_no == ""
    assert second.transport == "COURIER"


def test_parser_ignores_non_sale_rows_and_totals(tmp_path: Path) -> None:
    path = write_ledger(tmp_path / "ledger.xlsx", standard_rows())

    records = parse_pouncha_sales_workbook(path).records

    assert [record.voucher_no for record in records] == [
        "HST/26-27/1163",
        "HST/L/26-27/42",
    ]


@pytest.mark.parametrize(
    "order_text",
    [
        "1163  0  0  0",
        "ORDER NO. : 1163 0 0 0",
        "1163  0  0  0  0  0",
    ],
)
def test_parser_keeps_the_order_number_before_the_busy_zero_suffix(
    tmp_path: Path, order_text: str
) -> None:
    rows = [
        *PREAMBLE,
        HEADER,
        [date(2026, 10, 25), "Sale", "HST/26-27/1163", "ABC", 1000, 0],
        [None, None, None, order_text],
    ]
    path = write_ledger(tmp_path / "ledger.xlsx", rows)

    record = parse_pouncha_sales_workbook(path).records[0]

    assert record.order_no == "1163"


@pytest.mark.parametrize(
    "order_text",
    [
        "TRANSPORT : ROAD",
        "VEHICLE NO. : PB10AB1234",
        "STATION : LUDHIANA",
        "E-WAY BILL : 123456789",
        "TOTAL",
        "CLOSING BAL",
    ],
)
def test_parser_never_uses_a_label_row_as_the_order_number(
    tmp_path: Path, order_text: str
) -> None:
    rows = [
        *PREAMBLE,
        HEADER,
        [date(2026, 10, 25), "Sale", "HST/26-27/1163", "ABC", 1000, 0],
        [None, None, None, order_text],
    ]
    path = write_ledger(tmp_path / "ledger.xlsx", rows)

    record = parse_pouncha_sales_workbook(path).records[0]

    assert record.order_no == ""


def test_parser_does_not_leak_details_into_the_next_bill(tmp_path: Path) -> None:
    rows = [
        *PREAMBLE,
        HEADER,
        [date(2026, 10, 25), "Sale", "HST/26-27/1", "ABC", 1000, 0],
        [None, None, None, "TRANSPORT : ROAD"],
        [date(2026, 10, 25), "Sale", "HST/26-27/2", "XYZ", 1000, 0],
    ]
    path = write_ledger(tmp_path / "ledger.xlsx", rows)

    records = parse_pouncha_sales_workbook(path).records

    assert records[0].transport == "ROAD"
    assert records[1].transport == ""


def test_parser_reads_labels_and_values_from_separate_cells(
    tmp_path: Path,
) -> None:
    rows = [
        *PREAMBLE,
        HEADER,
        [date(2026, 10, 25), "Sale", "HST/26-27/1", "ABC", 1000, 0],
        [None, None, None, "TRANSPORT", "ROAD"],
        [None, None, None, "VEHICLE NO.", "PB10AB1234"],
        [None, None, None, "STATION", "Ludhiana"],
    ]
    path = write_ledger(tmp_path / "ledger.xlsx", rows)

    record = parse_pouncha_sales_workbook(path).records[0]

    assert record.transport == "ROAD"
    assert record.vehicle_no == "PB10AB1234"
    assert record.station == "LUDHIANA"


def test_parser_keeps_reading_details_when_a_detail_row_has_a_date(
    tmp_path: Path,
) -> None:
    rows = [
        *PREAMBLE,
        HEADER,
        [date(2026, 10, 25), "Sale", "HST/26-27/1", "ABC", 1000, 0],
        [date(2026, 10, 20), None, None, "TRANSPORT : ROAD"],
        [None, None, None, "STATION : LUDHIANA"],
    ]
    path = write_ledger(tmp_path / "ledger.xlsx", rows)

    record = parse_pouncha_sales_workbook(path).records[0]

    assert record.transport == "ROAD"
    assert record.station == "LUDHIANA"


def test_parser_requires_an_account_ledger_header(tmp_path: Path) -> None:
    path = write_ledger(
        tmp_path / "ledger.xlsx",
        [["H.S. TRADERS"], ["No header here"], [date(2026, 10, 25), "Sale", "X", "Y"]],
    )

    with pytest.raises(PounchaParseError, match="header row"):
        parse_pouncha_sales_workbook(path)


def test_parser_rejects_unsupported_workbook_types(tmp_path: Path) -> None:
    path = tmp_path / "ledger.xls"
    path.write_bytes(b"not supported")

    with pytest.raises(PounchaParseError, match="Unsupported"):
        parse_pouncha_sales_workbook(path)


def test_parser_rejects_an_unreadable_workbook(tmp_path: Path) -> None:
    path = tmp_path / "ledger.xlsx"
    path.write_bytes(b"not a real xlsx file")

    with pytest.raises(PounchaParseError, match="Could not read"):
        parse_pouncha_sales_workbook(path)


def test_parser_skips_duplicate_and_invalid_sale_rows(tmp_path: Path) -> None:
    rows = [
        *PREAMBLE,
        HEADER,
        [date(2026, 10, 25), "Sale", "HST/26-27/1", "ABC", 1000, 0],
        [date(2026, 10, 25), "Sale", "HST/26-27/1", "ABC", 1000, 0],
        [date(2026, 10, 25), "Sale", "", "ABC", 1000, 0],
        ["not a date", "Sale", "HST/26-27/2", "ABC", 1000, 0],
    ]
    path = write_ledger(tmp_path / "ledger.xlsx", rows)

    parsed = parse_pouncha_sales_workbook(path)

    assert [record.voucher_no for record in parsed.records] == ["HST/26-27/1"]
    assert len(parsed.warnings) == 3


def test_parser_returns_no_records_when_there_are_no_sales(tmp_path: Path) -> None:
    rows = [
        *PREAMBLE,
        HEADER,
        [date(2026, 10, 25), "Purchase", "PUR/26-27/1", "SUPPLIER", 0, 500],
    ]
    path = write_ledger(tmp_path / "ledger.xlsx", rows)

    parsed = parse_pouncha_sales_workbook(path)

    assert parsed.records == ()
    assert parsed.warnings == ()


def test_voucher_identity_canonicalizes_the_branch_series() -> None:
    assert voucher_identity("HST/L/26-27/42") == voucher_identity(
        "HSL-2026-2027-42"
    )
    assert voucher_identity("HST/26-27/42") != voucher_identity(
        "HST/L/26-27/42"
    )


def test_select_new_records_deduplicates_and_sorts() -> None:
    records = [
        PounchaSaleRecord(date(2026, 10, 26), "HST/26-27/10", "A"),
        PounchaSaleRecord(date(2026, 10, 25), "HST/L/26-27/2", "B"),
        PounchaSaleRecord(date(2026, 10, 25), "HST/26-27/2", "C"),
        PounchaSaleRecord(date(2026, 10, 26), "HST/26-27/10", "DUPLICATE"),
        PounchaSaleRecord(date(2026, 10, 25), "HST/26-27/1", "ALREADY"),
    ]

    fresh, already = select_new_records(
        records, {voucher_identity("HST/26-27/1")}
    )

    assert already == 2
    assert [record.voucher_no for record in fresh] == [
        "HST/26-27/2",
        "HST/L/26-27/2",
        "HST/26-27/10",
    ]


def test_rows_for_records_maps_columns_a_to_g() -> None:
    record = PounchaSaleRecord(
        date=date(2026, 10, 25),
        voucher_no="HST/26-27/1163",
        account="ABC TEXTILES",
        transport="ROAD",
        vehicle_no="PB10AB1234",
        station="LUDHIANA",
        order_no="1163",
    )

    assert rows_for_records([record]) == [
        [
            "25/10/2026",
            "HST/26-27/1163",
            "ABC TEXTILES",
            "ROAD",
            "PB10AB1234",
            "LUDHIANA",
            "1163",
        ]
    ]


def test_google_sheets_client_reads_column_b_without_a_header() -> None:
    client = GoogleSheetsClient(
        spreadsheet_id="sheet-id",
        tab_name="POUNCHA 26-27",
        service_account_file="service-account.json",
    )
    worksheet = FakeWorksheet(["HST/26-27/1", "", "HST/26-27/2"])
    client._worksheet = worksheet

    assert client.existing_voucher_keys() == {
        voucher_identity("HST/26-27/1"),
        voucher_identity("HST/26-27/2"),
    }
    assert client.append_rows([["25/10/2026", "HST/26-27/3"]]) == 1
    assert worksheet.appended == [["25/10/2026", "HST/26-27/3"]]


def test_google_sheets_client_requires_configuration() -> None:
    client = GoogleSheetsClient(
        spreadsheet_id="",
        tab_name="POUNCHA 26-27",
        service_account_file=None,
    )

    assert client.configured is False
    with pytest.raises(PounchaSheetError, match="not configured"):
        client.existing_voucher_keys()


def test_write_pouncha_archive_keeps_the_same_a_to_g_schema(
    tmp_path: Path,
) -> None:
    target = tmp_path / "Pouncha_Sales.xlsx"
    record = PounchaSaleRecord(
        date=date(2026, 10, 25),
        voucher_no="HST/26-27/1163",
        account="ABC TEXTILES",
        transport="ROAD",
        vehicle_no="PB10AB1234",
        station="LUDHIANA",
        order_no="1163",
    )

    write_pouncha_archive([record], target)

    workbook = load_workbook(target, read_only=True)
    try:
        rows = list(workbook.active.iter_rows(values_only=True))
    finally:
        workbook.close()
    assert rows[0] == OUTPUT_HEADERS
    assert rows[1] == tuple(record.as_sheet_row())


def _text_cells(row: tuple[Any, ...]) -> tuple[str, ...]:
    return tuple("" if value is None else str(value) for value in row)


def test_write_pouncha_archive_appends_without_touching_existing_rows(
    tmp_path: Path,
) -> None:
    target = tmp_path / "Pouncha_Sales.xlsx"
    existing = PounchaSaleRecord(
        date=date(2026, 10, 24),
        voucher_no="HST/26-27/1001",
        account="OLD PARTY",
    )
    added = PounchaSaleRecord(
        date=date(2026, 10, 25),
        voucher_no="HST/26-27/1002",
        account="NEW PARTY",
        station="LUDHIANA",
    )
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(list(OUTPUT_HEADERS))
    worksheet.append([*existing.as_sheet_row(), "P"])
    workbook.save(target)

    write_pouncha_archive([existing, added], target)

    workbook = load_workbook(target, read_only=True)
    try:
        rows = list(workbook.active.iter_rows(values_only=True))
    finally:
        workbook.close()
    assert _text_cells(rows[0])[:7] == tuple(OUTPUT_HEADERS)
    assert _text_cells(rows[1]) == (*existing.as_sheet_row(), "P")
    assert _text_cells(rows[2]) == (*added.as_sheet_row(), "")


def test_write_pouncha_archive_preserves_a_headerless_workbook(
    tmp_path: Path,
) -> None:
    target = tmp_path / "Pouncha_Sales.xlsx"
    existing = PounchaSaleRecord(
        date=date(2026, 10, 24),
        voucher_no="HST/26-27/1001",
        account="OLD PARTY",
    )
    added = PounchaSaleRecord(
        date=date(2026, 10, 25),
        voucher_no="HST/L/26-27/7",
        account="NEW PARTY",
    )
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append([*existing.as_sheet_row(), "BILTY AA GYI"])
    workbook.save(target)

    write_pouncha_archive([added], target)

    workbook = load_workbook(target, read_only=True)
    try:
        rows = list(workbook.active.iter_rows(values_only=True))
    finally:
        workbook.close()
    assert _text_cells(rows[0]) == (*existing.as_sheet_row(), "BILTY AA GYI")
    assert _text_cells(rows[1]) == (*added.as_sheet_row(), "")


def test_write_pouncha_archive_skips_rows_already_in_the_archive(
    tmp_path: Path,
) -> None:
    target = tmp_path / "Pouncha_Sales.xlsx"
    record = PounchaSaleRecord(
        date=date(2026, 10, 25),
        voucher_no="HST/26-27/1163",
        account="ABC TEXTILES",
    )
    write_pouncha_archive([record], target)
    before = target.read_bytes()

    write_pouncha_archive([record], target)

    assert target.read_bytes() == before


def test_scheduler_helpers_use_ist_midnight() -> None:
    assert start_of_today(NOW, IST) == datetime(2026, 10, 30, tzinfo=IST)
    assert next_midnight_after(NOW, IST) == datetime(2026, 10, 31, tzinfo=IST)


def test_should_catch_up_respects_active_runs_busy_and_success() -> None:
    assert should_catch_up(
        now=NOW,
        timezone=IST,
        last_success=None,
        active_run=None,
        busy_available=True,
    )
    assert not should_catch_up(
        now=NOW,
        timezone=IST,
        last_success=None,
        active_run=None,
        busy_available=False,
    )
    assert not should_catch_up(
        now=NOW,
        timezone=IST,
        last_success=None,
        active_run=make_run(status="queued"),
        busy_available=True,
    )
    assert not should_catch_up(
        now=NOW,
        timezone=IST,
        last_success=make_run(
            status="success",
            completed_at=datetime(2026, 10, 30, 0, 1, tzinfo=IST),
        ),
        active_run=None,
        busy_available=True,
    )
    assert should_catch_up(
        now=NOW,
        timezone=IST,
        last_success=make_run(
            status="success",
            completed_at=datetime(2026, 10, 29, 23, 59, tzinfo=IST),
        ),
        active_run=None,
        busy_available=True,
    )


def make_run(
    *,
    status: str,
    completed_at: datetime | None = None,
) -> Any:
    from app.domains.pouncha_sync.models import PounchaSyncRun

    return PounchaSyncRun(
        run_id="run",
        trigger_type="startup_catchup",
        start_date=date(2026, 10, 27),
        end_date=date(2026, 10, 30),
        exported_sale_count=0,
        already_in_sheet_count=0,
        appended_count=0,
        status=status,
        error_message=None,
        completed_at=completed_at,
    )


def test_scheduler_skips_quietly_when_busy_is_closed(tmp_path: Path) -> None:
    service = make_service(tmp_path, busy_available=False)
    scheduler = PounchaSyncScheduler(service, now=lambda: NOW)

    asyncio.run(scheduler._catch_up(NOW))

    assert service.repository.list_runs() == []
    assert scheduler.status().waiting_for_busy is True


def test_scheduler_runs_a_midnight_sync_when_busy_is_open(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    scheduler = PounchaSyncScheduler(service, now=lambda: NOW)

    asyncio.run(scheduler._run_midnight(NOW))

    runs = service.repository.list_runs()
    assert len(runs) == 1
    assert runs[0].trigger_type == PounchaTrigger.SCHEDULED_MIDNIGHT.value
    assert runs[0].status == "success"


def test_scheduler_does_not_repeat_a_successful_catch_up(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    run = service.repository.create_run(
        run_id="already-done",
        trigger_type=PounchaTrigger.STARTUP_CATCHUP.value,
        start_date=date(2026, 10, 27),
        end_date=date(2026, 10, 30),
    )
    service.repository.complete_run(
        run.run_id,
        status="success",
        completed_at=datetime(2026, 10, 30, 9, 0, tzinfo=IST),
    )
    scheduler = PounchaSyncScheduler(service, now=lambda: NOW)

    asyncio.run(scheduler._catch_up(NOW))

    assert len(service.repository.list_runs()) == 1


def test_service_upload_appends_only_new_rows_and_archives(
    tmp_path: Path,
) -> None:
    path = write_ledger(tmp_path / "ledger.xlsx", standard_rows())
    archive = tmp_path / "Pouncha_Sales.xlsx"
    sheets = FakeSheets(existing={voucher_identity("HST/26-27/1163")})
    service = make_service(
        tmp_path,
        sheets=sheets,
        pouncha_local_excel_path=archive,
    )

    run = service.run_upload(
        filename="ledger.xlsx",
        contents=path.read_bytes(),
        start_date=date(2026, 10, 25),
        end_date=date(2026, 10, 27),
    )

    assert run.status == "success"
    assert run.exported_sale_count == 2
    assert run.already_in_sheet_count == 1
    assert run.appended_count == 1
    assert sheets.appended == [
        [
            "27/10/2026",
            "HST/L/26-27/42",
            "XYZ TRADERS",
            "COURIER",
            "",
            "",
            "",
        ]
    ]
    assert not list((tmp_path / "uploads").glob("*"))
    assert archive.is_file()


def test_service_busy_run_marks_skipped_when_busy_is_closed(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path, exporter=FakeExporter(error=BusyNotRunningError("closed"))
    )

    run = asyncio.run(
        service.run_new_busy(
            trigger_type=PounchaTrigger.STARTUP_CATCHUP,
            start_date=date(2026, 10, 27),
            end_date=date(2026, 10, 30),
            skip_when_busy_closed=True,
        )
    )

    assert run.status == "skipped"
    assert run.error_message == "Waiting for BUSY 21."
    assert run.appended_count == 0


def test_service_busy_run_marks_failed_on_an_export_error(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path, exporter=FakeExporter(error=RuntimeError("BUSY exploded"))
    )

    with pytest.raises(RuntimeError, match="BUSY exploded"):
        asyncio.run(
            service.run_new_busy(
                trigger_type=PounchaTrigger.MANUAL_BUSY,
                start_date=date(2026, 10, 27),
                end_date=date(2026, 10, 30),
            )
        )

    run = service.repository.last_run()
    assert run is not None
    assert run.status == "failed"
    assert run.error_message == "BUSY exploded"


def test_service_nested_busy_lock_is_reentrant(tmp_path: Path) -> None:
    class NestedExporter(FakeExporter):
        def export_sales(
            self, start_date: date, end_date: date
        ) -> ParsedPounchaWorkbook:
            with acquire_busy_lock(tmp_path / "busy.lock", 0.5):
                return super().export_sales(start_date, end_date)

    service = make_service(tmp_path, exporter=NestedExporter())

    run = asyncio.run(
        service.run_new_busy(
            trigger_type=PounchaTrigger.MANUAL_BUSY,
            start_date=date(2026, 10, 27),
            end_date=date(2026, 10, 30),
        )
    )

    assert run.status == "success"


def test_repository_fails_stale_runs_after_a_restart(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    run = repository.create_run(
        run_id="stale",
        trigger_type=PounchaTrigger.MANUAL_BUSY.value,
        start_date=date(2026, 10, 27),
        end_date=date(2026, 10, 30),
    )
    repository.mark_running(run.run_id)
    assert repository.active_run() is not None

    assert repository.mark_stale_runs_failed() == 1

    assert repository.active_run() is None
    failed = repository.get_run(run.run_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error_message == "Interrupted by a backend restart."


def test_empty_local_archive_path_disables_the_archive(tmp_path: Path) -> None:
    settings = Settings(
        database_path=tmp_path / "pouncha.sqlite3",
        pouncha_local_excel_path="",
    )

    assert settings.pouncha_local_excel_path is None


def test_create_service_without_sheets_credentials_is_not_configured(
    tmp_path: Path,
) -> None:
    service = create_pouncha_sync_service(
        make_settings(tmp_path), make_repository(tmp_path)
    )

    assert service.sheets_configured is False
    assert service.configured is False


def make_api_app(service: PounchaSyncService) -> FastAPI:
    app = FastAPI()
    app.include_router(pouncha_routes.router, prefix="/api")
    app.state.pouncha_sync_service = service
    app.state.pouncha_scheduler = None
    return app


def test_api_status_and_manual_run_reaches_success(tmp_path: Path) -> None:
    sheets = FakeSheets()
    service = make_service(
        tmp_path,
        exporter=FakeExporter(
            parsed_workbook(
                PounchaSaleRecord(
                    date=date(2026, 10, 25),
                    voucher_no="HST/26-27/1163",
                    account="ABC TEXTILES",
                    transport="ROAD",
                    vehicle_no="PB10AB1234",
                    station="LUDHIANA",
                    order_no="1163",
                )
            )
        ),
        sheets=sheets,
    )
    app = make_api_app(service)

    with TestClient(app) as client:
        status = client.get("/api/pouncha-sync/status")
        assert status.status_code == 200
        assert status.json()["configured"] is True
        assert status.json()["scheduler"]["running"] is False

        queued = client.post(
            "/api/pouncha-sync/run",
            json={"start_date": "2026-10-27", "end_date": "2026-10-30"},
        )
        assert queued.status_code == 202
        assert queued.json()["status"] == "queued"
        run_id = queued.json()["run_id"]

        run: dict[str, Any] = {}
        for _ in range(200):
            response = client.get(f"/api/pouncha-sync/runs/{run_id}")
            assert response.status_code == 200
            run = response.json()
            if run["status"] in {"success", "failed", "skipped"}:
                break
            time.sleep(0.01)

    assert run["status"] == "success"
    assert run["appended_count"] == 1
    assert sheets.appended[0][1] == "HST/26-27/1163"


def test_api_run_rejects_an_active_run(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.repository.create_run(
        run_id="active",
        trigger_type=PounchaTrigger.MANUAL_BUSY.value,
        start_date=date(2026, 10, 27),
        end_date=date(2026, 10, 30),
    )
    app = make_api_app(service)

    with TestClient(app) as client:
        response = client.post("/api/pouncha-sync/run", json={})

    assert response.status_code == 409
    assert "already running" in response.json()["detail"]


def test_api_run_returns_503_when_sheets_are_not_configured(
    tmp_path: Path,
) -> None:
    sheets = FakeSheets()
    sheets._configured = False
    service = make_service(tmp_path, sheets=sheets)
    app = make_api_app(service)

    with TestClient(app) as client:
        response = client.post("/api/pouncha-sync/run", json={})

    assert response.status_code == 503


def test_api_upload_appends_and_rejects_bad_files(tmp_path: Path) -> None:
    path = write_ledger(tmp_path / "ledger.xlsx", standard_rows())
    sheets = FakeSheets()
    service = make_service(tmp_path, sheets=sheets)
    app = make_api_app(service)

    with TestClient(app) as client:
        uploaded = client.post(
            "/api/pouncha-sync/upload-excel",
            files={
                "file": (
                    "ledger.xlsx",
                    path.read_bytes(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
            data={"start_date": "2026-10-25", "end_date": "2026-10-27"},
        )
        rejected = client.post(
            "/api/pouncha-sync/upload-excel",
            files={"file": ("ledger.csv", b"not excel", "text/csv")},
        )

    assert uploaded.status_code == 200
    assert uploaded.json()["status"] == "success"
    assert uploaded.json()["appended_count"] == 2
    assert rejected.status_code == 400


def test_api_unknown_run_returns_404(tmp_path: Path) -> None:
    app = make_api_app(make_service(tmp_path))

    with TestClient(app) as client:
        response = client.get("/api/pouncha-sync/runs/does-not-exist")

    assert response.status_code == 404
