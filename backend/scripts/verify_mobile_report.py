"""Exercise the real report feature locally, with the same office warning and lock."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from app.config import Settings
from app.domains.mobile.desktop import desktop_lock, office_warning
from app.domains.mobile.reports import OutstandingExporter, verify_report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--party", required=True)
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    settings = Settings()
    with (
        desktop_lock(settings.database_path),
        TemporaryDirectory(prefix="outstanding-check-") as temp,
    ):
        directory = Path(temp)
        if not office_warning():
            print("Cancelled by office. BUSY was left untouched.")
            return
        path: Path = OutstandingExporter(settings).export_report(args.party, args.as_of, directory)
        print(json.dumps(verify_report(path, args.party, args.as_of)))
        print("Verified native PDF. Temporary report will be deleted after this check.")


if __name__ == "__main__":
    main()
