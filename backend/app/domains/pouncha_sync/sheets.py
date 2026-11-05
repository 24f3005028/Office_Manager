"""Narrow A:G-only Sheets adapter; no automatic retry of mutations."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import quote

from app.config import Settings
from app.domains.pouncha_sync.parser import Sale, SyncError, bill_key, parse_date, text

HEADERS = ["DATE", "BILL NO", "PARTY NAME", "TRANSPORT", "VEHICLE NO", "STATION", "NARRATION"]


@dataclass
class Snapshot:
    rows: list[list[str]]
    bills: dict[str, list[str]]
    last_date: date | None
    last_bill: str | None


def snapshot(rows: list[list[str]]) -> Snapshot:
    if not rows or [text(v).upper() for v in rows[0][:7]] != HEADERS:
        raise SyncError("The target tab's A:G headers do not match the Pouncha layout.")
    bills: dict[str, list[str]] = {}
    latest: date | None = None
    last_bill: str | None = None
    for number, row in enumerate(rows[1:], 2):
        cells = (row + [""] * 7)[:7]
        if not any(cells):
            if any(row[7:]):
                raise SyncError(f"Row {number} has remarks without bill data; check the sheet.")
            raise SyncError(f"Blank row {number} interrupts the bill table; check the sheet.")
        key = bill_key(cells[1])
        day = parse_date(cells[0])
        if key in bills:
            raise SyncError(f"Duplicate bill already in the sheet: {cells[1]}")
        if not cells[2]:
            raise SyncError(f"Missing party in sheet row {number}.")
        bills[key] = cells
        latest = max(latest, day) if latest else day
        last_bill = cells[1]
    return Snapshot(rows, bills, latest, last_bill)


def equivalent(left: list[str], right: list[str]) -> bool:
    return (
        parse_date(left[0]) == parse_date(right[0])
        and bill_key(left[1]) == bill_key(right[1])
        and [text(v) for v in left[2:7]] == [text(v) for v in right[2:7]]
    )


def compare(records: list[Sale], existing: Snapshot) -> tuple[list[Sale], list[str], int]:
    new, conflicts, count = [], [], 0
    for record in records:
        old = existing.bills.get(bill_key(record.bill))
        if old is None:
            new.append(record)
        else:
            count += 1
            if not equivalent(old, record.cells()):
                conflicts.append(record.bill)
    return new, conflicts, count


class GoogleSheet:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _request(self, method: str, suffix: str, **kwargs: Any) -> dict[str, Any]:
        try:
            credentials_module = importlib.import_module("google.oauth2.service_account")
            transport = importlib.import_module("google.auth.transport.requests")
            credentials = credentials_module.Credentials.from_service_account_file(
                str(self.settings.pouncha_credentials_path),
                scopes=["https://www.googleapis.com/auth/spreadsheets"],
            )
            with transport.AuthorizedSession(credentials) as session:
                response = session.request(
                    method,
                    "https://sheets.googleapis.com/v4/spreadsheets/"
                    + self.settings.pouncha_spreadsheet_id
                    + suffix,
                    timeout=20,
                    **kwargs,
                )
                response.raise_for_status()
                result: dict[str, Any] = response.json()
                return result
        except Exception as exc:
            raise SyncError(
                "Google Sheets request failed. Check access and connection; "
                "no automatic write retry was made."
            ) from exc

    @property
    def tab(self) -> str:
        return "'" + self.settings.pouncha_sheet_tab_name.replace("'", "''") + "'"

    def read(self) -> Snapshot:
        # Read H:Z too, to avoid appending into rows with manually entered remarks.
        data = self._request(
            "GET",
            "/values/" + quote(self.tab + "!A:Z", safe=""),
            params={"valueRenderOption": "FORMATTED_VALUE"},
        )
        rows = [[text(value) for value in row] for row in data.get("values", [])]
        return snapshot(rows)

    def append(self, records: list[Sale], before: Snapshot) -> str:
        data = self._request(
            "POST",
            "/values/" + quote(self.tab + "!A1:G" + str(len(before.rows)), safe="") + ":append",
            params={"valueInputOption": "RAW", "insertDataOption": "OVERWRITE"},
            json={"majorDimension": "ROWS", "values": [record.cells() for record in records]},
        )
        updated = data.get("updates", {})
        expected_start = len(before.rows) + 1
        expected = f"A{expected_start}:G{expected_start + len(records) - 1}"
        actual = str(updated.get("updatedRange", ""))
        if actual.split("!")[-1] != expected or updated.get("updatedRows") != len(records):
            raise SyncError("Unexpected Sheets append range. Check the sheet before another sync.")
        return actual
