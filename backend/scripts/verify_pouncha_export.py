"""Test BUSY's Excel export and cleanup without writing anything to Google Sheets."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from app.config import Settings
from app.domains.mobile.desktop import desktop_lock, office_warning
from app.domains.pouncha_sync.busy import BusyExporter
from app.domains.pouncha_sync.parser import parse_sales


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    settings = Settings()
    with desktop_lock(settings.database_path), TemporaryDirectory(prefix="pouncha-check-") as temp:
        if not office_warning():
            print("Cancelled by office. BUSY was left untouched.")
            return
        path = BusyExporter(settings).export(args.start, args.end, Path(temp))
        rows = parse_sales(path, settings.pouncha_company, args.start, args.end)
        print(f"Excel export verified: {len(rows)} bills. No Google Sheet writes.")
    print(f"Temporary Excel deleted: {not path.exists()}")


if __name__ == "__main__":
    main()
