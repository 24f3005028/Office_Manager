"""Minimal account/group catalogue imported from the user's account export."""

from __future__ import annotations

from contextlib import closing
from typing import Any

from app.domains.mobile.store import MobileStore, digest

# BUSY's Name column supplied by the owner. Under Group is not a search category.
GROUP_NAMES = (
    "Bank Accounts",
    "Bank O/D Account",
    "Capital Account",
    "Cash-in-hand",
    "Current Assets",
    "Current Liabilities",
    "Duties & Taxes",
    "Exempt Income",
    "Expenses (Direct/Mfg.)",
    "Expenses (Indirect/Admn.)",
    "Fixed Assets",
    "Income (Direct/Opr.)",
    "Income (Indirect)",
    "Investments",
    "Loans & Advances (Asset)",
    "Loans (Liability)",
    "Pre-Operative Expenses",
    "Profit & Loss",
    "Provisions/Expenses Payable",
    "Purchase",
    "Reserves & Surplus",
    "Revenue Accounts",
    "Sale",
    "Secured Loans",
    "Securities & Deposits (Asset)",
    "Stock-in-hand",
    "SUNDERY CREDITORS FOR BROKRAGE",
    "Sundry Creditors",
    "Sundry Debtors",
    "Suspense Account",
    "Unsecured Loans",
)


class AccountCatalogue:
    def __init__(self, store: MobileStore) -> None:
        self.database = store.database
        with closing(self.database.connect()) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS mobile_account_groups (
                  id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE);
                CREATE TABLE IF NOT EXISTS mobile_accounts (
                  id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                  group_id TEXT REFERENCES mobile_account_groups(id));
                CREATE INDEX IF NOT EXISTS mobile_accounts_by_group ON mobile_accounts(group_id);
            """)
            db.executemany(
                "INSERT OR IGNORE INTO mobile_account_groups VALUES (?,?)",
                [(self.group_id(name), name) for name in GROUP_NAMES],
            )
            db.execute(
                "INSERT OR IGNORE INTO mobile_accounts(id,name) SELECT id,name FROM mobile_parties"
            )

    @staticmethod
    def group_id(name: str) -> str:
        return digest("account-group:" + name.casefold())[:32]

    def import_rows(self, rows: list[dict[str, str]]) -> dict[str, int]:
        with closing(self.database.connect()) as db, db:
            before = db.execute("SELECT COUNT(*) FROM mobile_accounts").fetchone()[0]
            for row in rows:
                group_id = self.group_id(row["group"])
                db.execute(
                    "INSERT OR IGNORE INTO mobile_account_groups VALUES (?,?)",
                    (group_id, row["group"]),
                )
                db.execute(
                    "INSERT INTO mobile_accounts(id,name,group_id) VALUES (?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET name=excluded.name,group_id=excluded.group_id",
                    (digest(row["name"].casefold())[:32], row["name"], group_id),
                )
            count = db.execute("SELECT COUNT(*) FROM mobile_accounts").fetchone()[0]
            groups = db.execute("SELECT COUNT(*) FROM mobile_account_groups").fetchone()[0]
            return {"account_added": count - before, "accounts": count, "groups": groups}

    def groups(self, query: str = "") -> list[dict[str, Any]]:
        with closing(self.database.connect()) as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT g.id,g.name,COUNT(a.id) AS account_count FROM mobile_account_groups g "
                    "LEFT JOIN mobile_accounts a ON a.group_id=g.id "
                    "WHERE instr(lower(g.name),lower(?))>0 GROUP BY g.id "
                    "ORDER BY g.name COLLATE NOCASE",
                    (query,),
                )
            ]

    def accounts(self, query: str = "", group_id: str | None = None) -> list[dict[str, Any]]:
        with closing(self.database.connect()) as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT a.id,a.name,a.group_id,g.name AS group_name FROM mobile_accounts a "
                    "LEFT JOIN mobile_account_groups g ON g.id=a.group_id "
                    "WHERE instr(lower(a.name),lower(?))>0 AND (? IS NULL OR a.group_id=?) "
                    "ORDER BY a.name COLLATE NOCASE LIMIT 100",
                    (query, group_id, group_id),
                )
            ]

    def account(self, account_id: str) -> dict[str, str] | None:
        with closing(self.database.connect()) as db:
            row = db.execute("SELECT * FROM mobile_accounts WHERE id=?", (account_id,)).fetchone()
            return dict(row) if row else None

    def group(self, group_id: str) -> dict[str, str] | None:
        with closing(self.database.connect()) as db:
            row = db.execute(
                "SELECT * FROM mobile_account_groups WHERE id=?", (group_id,)
            ).fetchone()
            return dict(row) if row else None
