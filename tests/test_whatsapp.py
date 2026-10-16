from datetime import date, datetime

import pytest

from office_hub.whatsapp.command_parser import WhatsAppCommandError, parse_report_request
from office_hub.whatsapp.models import InboundWhatsAppMessage
from office_hub.whatsapp.service import acknowledgement, plan_help_request


def test_parse_profit_loss_with_explicit_period() -> None:
    request = parse_report_request(
        "What is the profit and loss from 2026-10-01 to 2026-10-31?",
        date(2026, 11, 3),
    )

    assert request.report_type == "profit_loss"
    assert request.start_date == "2026-10-01"
    assert request.end_date == "2026-10-31"


def test_parse_balance_sheet_defaults_to_current_month() -> None:
    request = parse_report_request("send balance sheet", date(2026, 2, 10))

    assert request.report_type == "balance_sheet"
    assert request.start_date == "2026-02-01"
    assert request.end_date == "2026-02-28"


def test_unknown_help_request_is_rejected() -> None:
    with pytest.raises(WhatsAppCommandError):
        parse_report_request("show me outstanding invoices", date(2026, 2, 10))


def test_help_acknowledgement_is_deterministic() -> None:
    message = InboundWhatsAppMessage(
        "message-1",
        "919999999999",
        "pnl today",
        datetime(2026, 10, 16),
    )
    request = plan_help_request(message)

    assert "Profit & Loss" in acknowledgement(message, request)
    assert "2026-10-16" in acknowledgement(message, request)
