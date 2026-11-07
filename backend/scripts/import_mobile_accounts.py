"""Import only BUSY account names and groups into the office app's own catalogue."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.config import Settings
from app.db import Database
from app.domains.mobile.account_catalogue import AccountCatalogue
from app.domains.mobile.accounts import account_rows
from app.domains.mobile.store import MobileStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    args = parser.parse_args()
    if args.workbook.stat().st_size > 10 * 1024 * 1024:
        raise SystemExit("The account export exceeds 10 MiB.")
    rows = account_rows(args.workbook.read_bytes())
    database = Database(Settings().database_path)
    database.initialize()
    store = MobileStore(database)
    trade = [
        row["name"]
        for row in rows
        if row["group"].casefold() in {"sundry debtors", "sundry creditors"}
    ]
    result = AccountCatalogue(store).import_rows(rows)
    result["trade_added"] = store.add_parties(trade)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
