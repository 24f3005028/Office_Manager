"""Help-chat planning and outbound delivery selection."""

from __future__ import annotations

from pathlib import Path

from ..config import Settings
from .cloud_api import WhatsAppCloudApiProvider
from .command_parser import parse_report_request
from .models import DeliveryReceipt, InboundWhatsAppMessage, ReportRequest
from .provider import DryRunWhatsAppProvider, WhatsAppProvider, WhatsAppProviderUnavailable


def plan_help_request(message: InboundWhatsAppMessage) -> ReportRequest:
    return parse_report_request(message.text, message.received_at.date())


def acknowledgement(message: InboundWhatsAppMessage, request: ReportRequest) -> str:
    return (
        f"I’m preparing the {request.display_name} report for {request.start_date} to "
        f"{request.end_date}. I’ll send the summary and Excel file when it is ready."
    )


def report_message(request: ReportRequest, totals: dict[str, float], review_required: bool) -> str:
    if request.report_type == "profit_loss":
        body = (
            f"{request.display_name} Summary\n\n"
            f"Period: {request.start_date} to {request.end_date}\n"
            f"Revenue: {totals.get('revenue', 0):,.2f}\n"
            f"Expenses: {totals.get('expenses', 0):,.2f}\n"
            f"Net Profit: {totals.get('net_profit', 0):,.2f}"
        )
    else:
        body = (
            f"{request.display_name} Summary\n\n"
            f"Period: {request.start_date} to {request.end_date}\n"
            f"Assets: {totals.get('assets', 0):,.2f}\n"
            f"Liabilities: {totals.get('liabilities', 0):,.2f}\n"
            f"Equity: {totals.get('equity', 0):,.2f}\n"
            f"Difference: {totals.get('balance_difference', 0):,.2f}"
        )
    if review_required:
        body += "\n\nReview required: the report did not fully reconcile."
    return body


def provider_for(settings: Settings) -> WhatsAppProvider:
    if settings.whatsapp_provider == "dry_run":
        return DryRunWhatsAppProvider()
    if settings.whatsapp_provider == "cloud_api":
        if not settings.allow_external_actions:
            raise WhatsAppProviderUnavailable("External actions are disabled")
        return WhatsAppCloudApiProvider(settings)
    raise WhatsAppProviderUnavailable(
        f"Unsupported WhatsApp provider: {settings.whatsapp_provider}"
    )


def send_report_result(
    settings: Settings,
    recipient_id: str,
    message: str,
    artifact: Path | None,
    idempotency_key: str,
) -> DeliveryReceipt:
    provider = provider_for(settings)
    receipt = provider.send_text(recipient_id, message, idempotency_key)
    if artifact is not None:
        return provider.send_document(
            recipient_id,
            artifact,
            "Detailed BUSY report",
            idempotency_key + ":document",
        )
    return receipt
