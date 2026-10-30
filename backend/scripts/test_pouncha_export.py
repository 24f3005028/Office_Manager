r"""Run one Pouncha Account Ledger export without writing to Google Sheets.

Use this after calibrating ``config/busy_ui_profile.json`` and before enabling
the daily scheduler:

    .\\.venv\\Scripts\\python.exe scripts/test_pouncha_export.py
    .\\.venv\\Scripts\\python.exe scripts/test_pouncha_export.py --keep-dir data\calibration

The script drives the same guarded BUSY export as the Pouncha sync, copies the
temporary workbook to ``--keep-dir`` for inspection, and parses it with the
production parser. It never connects to Google Sheets and never appends rows.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import Settings  # noqa: E402
from app.domains.busy_automation.errors import BusyAutomationError  # noqa: E402
from app.domains.busy_automation.profile import load_profile  # noqa: E402
from app.domains.busy_automation.recipes import (  # noqa: E402
    AccountLedgerSalesRecipe,
)
from app.domains.busy_automation.runner import (  # noqa: E402
    BusyAutomationConfig,
    BusyAutomationRequest,
    BusyExportRunner,
)
from app.domains.pouncha_sync.models import ParsedPounchaWorkbook  # noqa: E402
from app.domains.pouncha_sync.parser import (  # noqa: E402
    PounchaParseError,
    parse_pouncha_sales_workbook,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Export the BUSY Account Ledger Sales report and parse it without "
            "writing to Google Sheets."
        )
    )
    parser.add_argument(
        "--start-date",
        type=date.fromisoformat,
        default=None,
        help="Report start date (YYYY-MM-DD, default: today - 3 days).",
    )
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        default=None,
        help="Report end date (YYYY-MM-DD, default: today).",
    )
    parser.add_argument(
        "--keep-dir",
        type=Path,
        default=BACKEND_DIR / "data" / "pouncha_calibration",
        help="Directory for the inspection copy of the workbook.",
    )
    parser.add_argument(
        "--no-keep",
        action="store_true",
        help="Delete the inspection copy after parsing.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = Settings()
    profile = load_profile(settings.busy_ui_profile_path)
    sales_profile = profile.account_ledger_sales
    if not sales_profile.calibrated:
        print(
            "The Account Ledger Sales recipe is not calibrated. Open BUSY 21, "
            "run scripts/inspect_busy_ui.py --watch --controls, fill "
            f"{settings.busy_ui_profile_path}, and set "
            "account_ledger_sales.calibrated to true.",
            file=sys.stderr,
        )
        return 2

    end_date = args.end_date or date.today()
    start_date = args.start_date or (end_date - timedelta(days=3))
    if start_date > end_date:
        print("The start date is after the end date.", file=sys.stderr)
        return 2

    keep_dir = args.keep_dir.resolve()
    keep_dir.mkdir(parents=True, exist_ok=True)
    keep_path = keep_dir / (
        f"AccountLedger_Sales_{start_date:%Y%m%d}_{end_date:%Y%m%d}_"
        f"{datetime.now():%Y%m%d-%H%M%S}.xlsx"
    )

    config = BusyAutomationConfig.from_settings(settings)
    runner = BusyExportRunner(config)

    def inspect(exported: Path) -> ParsedPounchaWorkbook:
        shutil.copy2(exported, keep_path)
        parsed = parse_pouncha_sales_workbook(exported)
        print(f"Workbook copy: {keep_path}")
        print(f"Sheet: {parsed.sheet_name}")
        print(f"Sale bills parsed: {len(parsed.records)}")
        for record in parsed.records[:10]:
            print(f"  {record.date_text}  {record.voucher_no}  {record.account}")
        if len(parsed.records) > 10:
            print(f"  ... {len(parsed.records) - 10} more")
        if parsed.warnings:
            print("Warnings:")
            for warning in parsed.warnings:
                print(f"  - {warning}")
        return parsed

    try:
        parsed, outcome = runner.run(
            BusyAutomationRequest(
                start_date=start_date,
                end_date=end_date,
                category="bills",
            ),
            recipe=AccountLedgerSalesRecipe(sales_profile),
            consumer=inspect,
            filename_prefix="pouncha_calibration",
        )
    except (BusyAutomationError, PounchaParseError, ValueError) as exc:
        print(f"Pouncha calibration export failed: {exc}", file=sys.stderr)
        return 1

    print(f"Requested workbook: {outcome.requested_path}")
    print(f"BUSY wrote: {outcome.exported_path}")
    print(f"Duration: {outcome.duration_sec:.1f}s")
    if args.no_keep:
        keep_path.unlink(missing_ok=True)
        print("Inspection copy removed.")
    else:
        print(f"Inspection copy kept at: {keep_path}")
    print(f"Parsed sale bills: {len(parsed.records)}")
    print("Google Sheets was not contacted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
