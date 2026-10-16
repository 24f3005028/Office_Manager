"""Provider protocol and fail-safe dry-run implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .models import DeliveryReceipt


class WhatsAppProvider(Protocol):
    def send_text(self, recipient_id: str, body: str, idempotency_key: str) -> DeliveryReceipt:
        ...

    def send_document(
        self,
        recipient_id: str,
        file_path: Path,
        caption: str,
        idempotency_key: str,
    ) -> DeliveryReceipt:
        ...


class WhatsAppProviderUnavailable(RuntimeError):
    """Raised when live delivery was requested without a configured provider."""


class DryRunWhatsAppProvider:
    """Never performs network activity; useful for local acceptance tests."""

    def send_text(self, recipient_id: str, body: str, idempotency_key: str) -> DeliveryReceipt:
        del body
        return DeliveryReceipt("dry_run", detail=f"Text planned for {recipient_id}")

    def send_document(
        self,
        recipient_id: str,
        file_path: Path,
        caption: str,
        idempotency_key: str,
    ) -> DeliveryReceipt:
        del caption
        return DeliveryReceipt(
            "dry_run",
            detail=f"Document {file_path.name} planned for {recipient_id}",
        )
