"""Client for the local WhatsApp bridge HTTP API."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx

SendOutcome = Literal["not_started", "unknown"]


@dataclass(frozen=True, slots=True)
class SendReceipt:
    """The bridge accepted the send; this is not a delivery acknowledgment."""

    operation_id: str
    message_id: str


class BridgeSendError(RuntimeError):
    """A failed bridge call with the real reason, safe to persist and display."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        retryable: bool,
        outcome: SendOutcome,
        session_unavailable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.outcome = outcome
        self.session_unavailable = session_unavailable


def _format_bridge_error(exc: httpx.HTTPStatusError) -> BridgeSendError:
    response = exc.response
    status_code = response.status_code
    detail = ""
    payload: Any = None
    try:
        payload = response.json()
        if isinstance(payload, Mapping) and isinstance(payload.get("error"), str):
            detail = payload["error"].strip()
    except ValueError:
        detail = ""
    if not detail:
        detail = response.text.strip()[:200] if response.text else ""
    # HTTP status alone cannot prove that an external send did not start.
    classified = (
        isinstance(payload, Mapping)
        and isinstance(payload.get("error"), str)
        and isinstance(payload.get("code"), str)
        and bool(payload["code"])
        and isinstance(payload.get("retryable"), bool)
        and payload.get("outcome") in ("not_started", "unknown")
    )
    code = str(payload["code"]) if classified else "UNCLASSIFIED_BRIDGE_ERROR"
    outcome: SendOutcome = (
        "not_started" if classified and payload["outcome"] == "not_started" else "unknown"
    )
    retryable = bool(payload["retryable"]) if classified else False
    return BridgeSendError(
        detail or f"WhatsApp bridge returned HTTP status {status_code}",
        code=code,
        retryable=retryable,
        outcome=outcome,
        session_unavailable=outcome == "not_started" and retryable and (
            status_code == 503 or code.upper() in {
                "NOT_READY", "SESSION_NOT_READY", "BRIDGE_NOT_READY", "GENERATION_MISMATCH",
                "STALE_GENERATION", "STALE_SESSION",
            }
        ),
    )


def classify_send_error(exc: Exception) -> BridgeSendError:
    if isinstance(exc, BridgeSendError):
        return exc
    if isinstance(exc, httpx.HTTPStatusError):
        return _format_bridge_error(exc)
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)):
        return BridgeSendError(
            "Could not connect to the WhatsApp bridge", code="BRIDGE_CONNECT_FAILED",
            retryable=True, outcome="not_started",
        )
    # Read/write/protocol failures can occur after the external send has begun.
    return BridgeSendError(
        "WhatsApp send outcome is unknown; review before sending again",
        code="SEND_OUTCOME_UNKNOWN", retryable=False, outcome="unknown",
    )


def parse_receipt(payload: Any, operation_id: str) -> SendReceipt:
    if (
        isinstance(payload, Mapping)
        and payload.get("status") == "sent"
        and payload.get("operation_id") == operation_id
        and isinstance(payload.get("message_id"), str)
        and payload["message_id"].strip()
    ):
        return SendReceipt(operation_id=operation_id, message_id=payload["message_id"])
    raise BridgeSendError(
        "WhatsApp bridge returned an invalid send receipt; review before sending again",
        code="INVALID_SEND_RECEIPT", retryable=False, outcome="unknown",
    )


class WhatsAppBridge(Protocol):
    async def start(self) -> Mapping[str, Any]: ...

    async def reconnect(self) -> Mapping[str, Any]: ...

    async def set_allowed_roots(self, roots: Sequence[str]) -> None: ...

    async def send_text(
        self, *, recipient: str, text: str, operation_id: str, generation: int | None = None,
    ) -> SendReceipt: ...

    async def send_document(
        self,
        *,
        recipient: str,
        file_path: Path,
        message: str | None,
        operation_id: str,
        generation: int | None = None,
    ) -> SendReceipt: ...

    async def status(self) -> Mapping[str, Any]: ...

    async def contacts(self) -> Any: ...

    async def qr(self) -> tuple[bytes, str]: ...


class HttpWhatsAppBridge:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 30.0,
        api_key: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"x-api-key": api_key} if api_key else None
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout_seconds, headers=headers,
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def send_text(
        self, *, recipient: str, text: str, operation_id: str, generation: int | None = None,
    ) -> SendReceipt:
        return await self._post_bridge_json(
            "/send-text",
            {"contact_id": recipient, "text": text, "operation_id": operation_id,
             **({"generation": generation} if generation is not None else {})},
        )

    async def send_document(
        self,
        *,
        recipient: str,
        file_path: Path,
        message: str | None,
        operation_id: str,
        generation: int | None = None,
    ) -> SendReceipt:
        # The file name is not sent: the bridge reads it from the validated path so the
        # delivered document always keeps the real file's name.
        return await self._post_bridge_json(
            "/send-document",
            {
                "contact_id": recipient,
                "file_path": str(file_path),
                "caption": message or None,
                "operation_id": operation_id,
                **({"generation": generation} if generation is not None else {}),
            },
        )

    async def _post_bridge_json(self, path: str, payload: Mapping[str, Any]) -> SendReceipt:
        try:
            response = await self._client.post(path, json=payload)
            response.raise_for_status()
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            raise classify_send_error(exc) from exc
        try:
            body = response.json()
        except ValueError:
            body = None
        return parse_receipt(body, str(payload["operation_id"]))

    async def status(self) -> Mapping[str, Any]:
        response = await self._client.get("/status")
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {"status": payload}

    async def start(self) -> Mapping[str, Any]:
        response = await self._client.post("/start")
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {"status": payload}

    async def reconnect(self) -> Mapping[str, Any]:
        response = await self._client.post("/reconnect")
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {"status": payload}

    async def set_allowed_roots(self, roots: Sequence[str]) -> None:
        response = await self._client.put("/allowed-roots", json={"roots": list(roots)})
        response.raise_for_status()

    async def contacts(self) -> Any:
        response = await self._client.get("/contacts")
        response.raise_for_status()
        return response.json()

    async def qr(self) -> tuple[bytes, str]:
        response = await self._client.get("/qr")
        response.raise_for_status()
        media_type = response.headers.get("content-type", "image/png").split(";", 1)[0]
        return response.content, media_type
