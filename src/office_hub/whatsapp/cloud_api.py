"""Minimal WhatsApp Cloud API provider.

Network delivery is only selected when the application is explicitly configured for ``cloud_api``
and external actions are enabled. Credentials are read from SecretStr settings and never logged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import httpx

from ..config import Settings
from .models import DeliveryReceipt
from .provider import WhatsAppProviderUnavailable


class WhatsAppCloudApiProvider:
    def __init__(self, settings: Settings) -> None:
        token = settings.whatsapp_cloud_access_token
        phone_number_id = settings.whatsapp_cloud_phone_number_id
        if token is None or phone_number_id is None:
            raise WhatsAppProviderUnavailable(
                "WhatsApp Cloud API requires access token and phone number ID settings"
            )
        self._token = token.get_secret_value()
        self._phone_number_id = phone_number_id
        self._base_url = f"https://graph.facebook.com/v20.0/{phone_number_id}"

    def send_text(self, recipient_id: str, body: str, idempotency_key: str) -> DeliveryReceipt:
        response = self._request(
            "/messages",
            {
                "messaging_product": "whatsapp",
                "to": recipient_id,
                "type": "text",
                "text": {"preview_url": False, "body": body},
            },
            idempotency_key,
        )
        messages = response.get("messages", [])
        message_id = messages[0].get("id") if isinstance(messages, list) and messages else None
        return DeliveryReceipt("sent", message_id if isinstance(message_id, str) else None)

    def send_document(
        self,
        recipient_id: str,
        file_path: Path,
        caption: str,
        idempotency_key: str,
    ) -> DeliveryReceipt:
        if not file_path.is_file():
            raise WhatsAppProviderUnavailable(f"Document does not exist: {file_path}")
        headers = {"Authorization": f"Bearer {self._token}"}
        with file_path.open("rb") as file_handle:
            upload = httpx.post(
                f"{self._base_url}/media",
                headers=headers,
                files={
                    "file": (
                        file_path.name,
                        file_handle,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
                data={
                    "messaging_product": "whatsapp",
                    "type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                },
                timeout=60,
            )
        upload.raise_for_status()
        media_id = upload.json()["id"]
        response = self._request(
            "/messages",
            {
                "messaging_product": "whatsapp",
                "to": recipient_id,
                "type": "document",
                "document": {"id": media_id, "caption": caption, "filename": file_path.name},
            },
            idempotency_key,
        )
        messages = response.get("messages", [])
        message_id = messages[0].get("id") if isinstance(messages, list) and messages else None
        return DeliveryReceipt("sent", message_id if isinstance(message_id, str) else None)

    def _request(
        self,
        path: str,
        payload: dict[str, object],
        idempotency_key: str,
    ) -> dict[str, Any]:
        response = httpx.post(
            f"{self._base_url}{path}",
            headers={
                "Authorization": f"Bearer {self._token}",
                "X-Idempotency-Key": idempotency_key,
            },
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        return cast(dict[str, Any], response.json())
