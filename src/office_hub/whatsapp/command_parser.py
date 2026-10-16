"""Conservative parser for the first WhatsApp financial-help commands."""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, timedelta

from .models import ReportRequest

_RANGE_PATTERN = re.compile(r"(20\d{2}-\d{2}-\d{2})\s*(?:to|through|-)\s*(20\d{2}-\d{2}-\d{2})")
_DATE_PATTERN = re.compile(r"20\d{2}-\d{2}-\d{2}")


class WhatsAppCommandError(ValueError):
    """Raised when a financial-help message is ambiguous or invalid."""


def parse_report_request(text: str, today: date | None = None) -> ReportRequest:
    """Parse only explicit supported report intents and ISO date ranges.

    If no period is supplied, the current calendar month is used and the acknowledgement says so.
    This avoids guessing arbitrary accounting periods from natural language.
    """

    normalized = " ".join(text.casefold().split())
    if "balance sheet" in normalized:
        report_type = "balance_sheet"
        display_name = "Balance Sheet"
    elif any(term in normalized for term in ("profit and loss", "profit & loss", "p&l", "pnl")):
        report_type = "profit_loss"
        display_name = "Profit & Loss"
    else:
        raise WhatsAppCommandError(
            "Ask for Profit and Loss or Balance Sheet, optionally with an ISO date range."
        )

    current = today or date.today()
    start, end = _parse_period(normalized, current)
    if end < start:
        raise WhatsAppCommandError("The report end date cannot be before its start date.")
    return ReportRequest(report_type, start.isoformat(), end.isoformat(), display_name)


def _parse_period(text: str, today: date) -> tuple[date, date]:
    range_match = _RANGE_PATTERN.search(text)
    if range_match:
        return date.fromisoformat(range_match.group(1)), date.fromisoformat(range_match.group(2))

    try:
        dates = [date.fromisoformat(value) for value in _DATE_PATTERN.findall(text)]
    except ValueError as exc:
        raise WhatsAppCommandError("Use valid ISO dates such as 2026-10-01.") from exc
    if len(dates) == 2:
        return dates[0], dates[1]
    if len(dates) == 1:
        return dates[0], dates[0]
    if "today" in text:
        return today, today
    if "yesterday" in text:
        previous = today - timedelta(days=1)
        return previous, previous
    if "this year" in text:
        return date(today.year, 1, 1), date(today.year, 12, 31)

    month_start = date(today.year, today.month, 1)
    month_end = date(today.year, today.month, monthrange(today.year, today.month)[1])
    return month_start, month_end
