"""Pouncha daily sales sync models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum


class PounchaTrigger(StrEnum):
    SCHEDULED_MIDNIGHT = "scheduled_midnight"
    STARTUP_CATCHUP = "startup_catchup"
    MANUAL_BUSY = "manual_busy"
    MANUAL_EXCEL = "manual_excel"


class PounchaRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class PounchaSaleRecord:
    """One Sale bill, mapped to Columns A-G of ``POUNCHA 26-27``."""

    date: date
    voucher_no: str
    account: str
    transport: str = ""
    vehicle_no: str = ""
    station: str = ""
    order_no: str = ""

    @property
    def date_text(self) -> str:
        return self.date.strftime("%d/%m/%Y")

    def as_sheet_row(self) -> list[str]:
        return [
            self.date_text,
            self.voucher_no,
            self.account,
            self.transport,
            self.vehicle_no,
            self.station,
            self.order_no,
        ]


@dataclass(frozen=True, slots=True)
class ParsedPounchaWorkbook:
    records: tuple[PounchaSaleRecord, ...]
    warnings: tuple[str, ...]
    sheet_name: str


@dataclass(frozen=True, slots=True)
class PounchaSyncRun:
    run_id: str
    trigger_type: str
    start_date: date
    end_date: date
    exported_sale_count: int
    already_in_sheet_count: int
    appended_count: int
    status: str
    error_message: str | None
    warnings: tuple[str, ...] = ()
    started_at: datetime | None = None
    completed_at: datetime | None = None
    extra: dict[str, str] = field(default_factory=dict)
