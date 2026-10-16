"""Small transport models used by inbound and outbound WhatsApp flows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class InboundWhatsAppMessage:
    provider_message_id: str
    sender_id: str
    text: str
    received_at: datetime


@dataclass(frozen=True)
class DeliveryReceipt:
    status: str
    provider_message_id: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class ReportRequest:
    report_type: str
    start_date: str
    end_date: str
    display_name: str


@dataclass(frozen=True)
class WhatsAppResponse:
    recipient_id: str
    text: str
    document: Path | None = None
