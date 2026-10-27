"""SQLite-backed BUSY voucher index and sync-batch history."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, date, datetime

from app.db import Database
from app.domains.busy_ledger.parser import ParsedLedgerRow


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    id: int
    category: str
    raw_voucher_no: str
    canonical_series: str
    fy: str
    serial: int
    voucher_date: date
    party_name: str
    normalized_party: str


@dataclass(frozen=True, slots=True)
class BusyCategoryStatus:
    category: str
    total_vouchers: int
    min_date: date | None
    max_date: date | None


@dataclass(frozen=True, slots=True)
class BusyLedgerStatus:
    last_sync_at: datetime | None
    last_sync_filename: str | None
    total_vouchers: int
    categories: tuple[BusyCategoryStatus, ...]


class BusyLedgerRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def store_import(
        self,
        *,
        filename: str,
        rows: Sequence[ParsedLedgerRow],
        status: str = "completed",
    ) -> int:
        """Upsert parsed rows and record one sync batch in a single transaction."""

        now = datetime.now(UTC).isoformat()
        dates = [row.voucher_date for row in rows]
        min_date = min(dates).isoformat() if dates else None
        max_date = max(dates).isoformat() if dates else None
        with closing(self.database.connect()) as connection, connection:
            for row in rows:
                connection.execute(
                    "INSERT INTO busy_voucher_index ("
                    "category, raw_voucher_no, canonical_series, fy, serial, voucher_date, "
                    "party_name, normalized_party, imported_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(category, canonical_series, fy, serial, party_name) "
                    "DO UPDATE SET "
                    "raw_voucher_no = excluded.raw_voucher_no, "
                    "voucher_date = excluded.voucher_date, "
                    "normalized_party = excluded.normalized_party, "
                    "imported_at = excluded.imported_at",
                    (
                        row.category,
                        row.raw_voucher_no,
                        row.canonical_series,
                        row.fy,
                        row.serial,
                        row.voucher_date.isoformat(),
                        row.party_name,
                        row.normalized_party,
                        now,
                    ),
                )
            connection.execute(
                "INSERT INTO busy_sync_batches "
                "(filename, imported_at, row_count, min_date, max_date, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (filename, now, len(rows), min_date, max_date, status),
            )
        return len(rows)

    def record_failed_import(self, *, filename: str, error: str) -> None:
        now = datetime.now(UTC).isoformat()
        with closing(self.database.connect()) as connection, connection:
            connection.execute(
                "INSERT INTO busy_sync_batches "
                "(filename, imported_at, row_count, min_date, max_date, status) "
                "VALUES (?, ?, 0, NULL, NULL, ?)",
                (filename, now, f"failed: {error}"[:500]),
            )

    def load_entries(self, categories: Iterable[str] | None = None) -> dict[
        tuple[str, int], list[LedgerEntry]
    ]:
        selected = tuple(dict.fromkeys(categories or ()))
        query = (
            "SELECT id, category, raw_voucher_no, canonical_series, fy, serial, "
            "voucher_date, party_name, normalized_party FROM busy_voucher_index"
        )
        parameters: tuple[object, ...] = ()
        if selected:
            placeholders = ", ".join("?" for _ in selected)
            query += f" WHERE category IN ({placeholders})"
            parameters = selected
        query += " ORDER BY category, serial, id"
        entries: dict[tuple[str, int], list[LedgerEntry]] = {}
        with closing(self.database.connect()) as connection:
            for row in connection.execute(query, parameters).fetchall():
                entry = self._entry_from_row(row)
                entries.setdefault((entry.category, entry.serial), []).append(entry)
        return entries

    def search(
        self, category: str, serial: int, fy: str | None = None
    ) -> list[LedgerEntry]:
        query = (
            "SELECT id, category, raw_voucher_no, canonical_series, fy, serial, "
            "voucher_date, party_name, normalized_party FROM busy_voucher_index "
            "WHERE category = ? AND serial = ?"
        )
        parameters: list[object] = [category, serial]
        if fy:
            query += " AND (fy = ? OR fy = '')"
            parameters.append(fy)
        query += " ORDER BY id"
        with closing(self.database.connect()) as connection:
            return [
                self._entry_from_row(row)
                for row in connection.execute(query, parameters).fetchall()
            ]

    def status(self) -> BusyLedgerStatus:
        with closing(self.database.connect()) as connection:
            latest = connection.execute(
                "SELECT filename, imported_at FROM busy_sync_batches "
                "WHERE status = 'completed' ORDER BY imported_at DESC, id DESC LIMIT 1"
            ).fetchone()
            total_row = connection.execute(
                "SELECT COUNT(*) AS total FROM busy_voucher_index"
            ).fetchone()
            category_rows = connection.execute(
                "SELECT category, COUNT(*) AS total, MIN(voucher_date) AS min_date, "
                "MAX(voucher_date) AS max_date FROM busy_voucher_index "
                "GROUP BY category ORDER BY category"
            ).fetchall()

        categories: list[BusyCategoryStatus] = []
        for row in category_rows:
            categories.append(
                BusyCategoryStatus(
                    category=str(row["category"]),
                    total_vouchers=int(row["total"]),
                    min_date=_parse_iso_date(row["min_date"]),
                    max_date=_parse_iso_date(row["max_date"]),
                )
            )
        last_sync_at = None
        last_sync_filename = None
        if latest is not None:
            last_sync_filename = str(latest["filename"])
            try:
                last_sync_at = datetime.fromisoformat(str(latest["imported_at"]))
            except ValueError:
                last_sync_at = None
        return BusyLedgerStatus(
            last_sync_at=last_sync_at,
            last_sync_filename=last_sync_filename,
            total_vouchers=int(total_row["total"]) if total_row is not None else 0,
            categories=tuple(categories),
        )

    @staticmethod
    def _entry_from_row(row: sqlite3.Row) -> LedgerEntry:
        voucher_date = _parse_iso_date(row["voucher_date"])
        if voucher_date is None:
            raise ValueError(f"Invalid voucher date in BUSY index: {row['voucher_date']}")
        return LedgerEntry(
            id=int(row["id"]),
            category=str(row["category"]),
            raw_voucher_no=str(row["raw_voucher_no"]),
            canonical_series=str(row["canonical_series"]),
            fy=str(row["fy"]),
            serial=int(row["serial"]),
            voucher_date=voucher_date,
            party_name=str(row["party_name"]),
            normalized_party=str(row["normalized_party"]),
        )


def _parse_iso_date(value: object) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None
