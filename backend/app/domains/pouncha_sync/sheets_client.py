"""Google Sheets append and deduplication for ``POUNCHA 26-27``."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from typing import Any, Protocol

from app.domains.pouncha_sync.models import PounchaSaleRecord
from app.domains.pouncha_sync.parser import (
    voucher_identity,
    voucher_sort_key,
)

logger = logging.getLogger(__name__)

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
VOUCHER_COLUMN = 2
FIRST_COLUMN = 1
LAST_COLUMN = 7


class PounchaSheetError(RuntimeError):
    """Raised when the Google Sheet cannot be read or appended."""


class PounchaSheetClient(Protocol):
    @property
    def configured(self) -> bool: ...

    def existing_voucher_keys(self) -> set[str]: ...

    def append_rows(self, rows: Sequence[Sequence[str]]) -> int: ...


class GoogleSheetsClient:
    """A minimal gspread client for the headerless ``POUNCHA 26-27`` tab."""

    def __init__(
        self,
        *,
        spreadsheet_id: str,
        tab_name: str,
        service_account_file: str | None,
    ) -> None:
        self.spreadsheet_id = spreadsheet_id.strip()
        self.tab_name = tab_name.strip()
        self.service_account_file = service_account_file
        self._worksheet: Any | None = None

    @property
    def configured(self) -> bool:
        return bool(
            self.spreadsheet_id and self.tab_name and self.service_account_file
        )

    def existing_voucher_keys(self) -> set[str]:
        worksheet = self._open_worksheet()
        try:
            values = worksheet.col_values(VOUCHER_COLUMN)
        except Exception as exc:
            raise PounchaSheetError(
                f"Could not read Column B from the {self.tab_name!r} tab: {exc}"
            ) from exc
        return {voucher_identity(value) for value in values if str(value).strip()}

    def append_rows(self, rows: Sequence[Sequence[str]]) -> int:
        if not rows:
            return 0
        worksheet = self._open_worksheet()
        try:
            worksheet.append_rows(
                [list(row) for row in rows],
                value_input_option="USER_ENTERED",
            )
        except Exception as exc:
            raise PounchaSheetError(
                f"Could not append {len(rows)} row(s) to the {self.tab_name!r} tab: {exc}"
            ) from exc
        return len(rows)

    def _open_worksheet(self) -> Any:
        if not self.configured:
            raise PounchaSheetError(
                "Google Sheets is not configured. Set POUNCHA_SPREADSHEET_ID and "
                "GOOGLE_SERVICE_ACCOUNT_FILE, then share the sheet with the "
                "service-account email as Editor."
            )
        if self._worksheet is not None:
            return self._worksheet
        try:
            import gspread
            from google.oauth2.service_account import Credentials
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise PounchaSheetError(
                "gspread and google-auth are required for Pouncha sync."
            ) from exc

        try:
            credentials = Credentials.from_service_account_file(  # type: ignore[no-untyped-call]
                self.service_account_file, scopes=[SHEETS_SCOPE]
            )
            client = gspread.authorize(credentials)
            spreadsheet = client.open_by_key(self.spreadsheet_id)
        except Exception as exc:
            raise PounchaSheetError(
                "Could not open the Pouncha Google Sheet. Check "
                "POUNCHA_SPREADSHEET_ID and the service-account JSON: "
                f"{exc}"
            ) from exc
        try:
            self._worksheet = spreadsheet.worksheet(self.tab_name)
        except Exception as exc:
            raise PounchaSheetError(
                f"The Google Sheet does not contain a {self.tab_name!r} tab. "
                "Create or rename the tab; the sync never creates it "
                f"automatically. ({exc})"
            ) from exc
        return self._worksheet


def select_new_records(
    records: Iterable[PounchaSaleRecord],
    existing_keys: set[str],
) -> tuple[list[PounchaSaleRecord], int]:
    """Return records not already in Column B, in append order.

    Duplicates are removed both against the sheet and within the batch. The
    result is sorted by date, HST before HST/L, then serial number.
    """

    known = set(existing_keys)
    fresh: list[PounchaSaleRecord] = []
    already = 0
    for record in records:
        key = voucher_identity(record.voucher_no)
        if key in known:
            already += 1
            continue
        known.add(key)
        fresh.append(record)
    fresh.sort(key=voucher_sort_key)
    return fresh, already


def rows_for_records(records: Iterable[PounchaSaleRecord]) -> list[list[str]]:
    return [record.as_sheet_row() for record in records]
