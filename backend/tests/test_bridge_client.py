import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from app.integrations.whatsapp.client import BridgeSendError, HttpWhatsAppBridge, SendReceipt


async def test_send_payloads_and_receipts_use_the_same_stable_operation_id(tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append((request.url.path, payload))
        assert request.headers["x-api-key"] == "fixture-key"
        if request.url.path == "/allowed-roots":
            return httpx.Response(200, json={"roots": payload["roots"]})
        return httpx.Response(200, json={
            "status": "sent", "operation_id": payload["operation_id"], "message_id": "receipt-1",
        })

    bridge = HttpWhatsAppBridge(
        "http://fixture-bridge", api_key="fixture-key", transport=httpx.MockTransport(handler),
    )
    try:
        first = await bridge.send_text(
            recipient="fixture@c.us", text="intro", operation_id="intro-1", generation=42,
        )
        second = await bridge.send_document(
            recipient="fixture@c.us", file_path=tmp_path / "Bill 1.pdf", message=None,
            operation_id="pdf-1", generation=42,
        )
        repeated = await bridge.send_document(
            recipient="fixture@c.us", file_path=tmp_path / "Bill 1.pdf", message=None,
            operation_id="pdf-1", generation=43,
        )
        await bridge.set_allowed_roots([])
    finally:
        await bridge.close()
    assert first == SendReceipt("intro-1", "receipt-1")
    assert second == repeated == SendReceipt("pdf-1", "receipt-1")
    assert calls[:3] == [
        ("/send-text", {
            "contact_id": "fixture@c.us", "text": "intro", "operation_id": "intro-1",
            "generation": 42,
        }),
        ("/send-document", {
            "contact_id": "fixture@c.us", "file_path": str(tmp_path / "Bill 1.pdf"),
            "caption": None, "operation_id": "pdf-1", "generation": 42,
        }),
        ("/send-document", {
            "contact_id": "fixture@c.us", "file_path": str(tmp_path / "Bill 1.pdf"),
            "caption": None, "operation_id": "pdf-1", "generation": 43,
        }),
    ]
    assert calls[3] == ("/allowed-roots", {"roots": []})


@pytest.mark.parametrize(("exception", "outcome", "retryable"), [
    (httpx.ConnectError, "not_started", True),
    (httpx.ConnectTimeout, "not_started", True),
    (httpx.PoolTimeout, "not_started", True),
    (httpx.ReadTimeout, "unknown", False),
    (httpx.WriteTimeout, "unknown", False),
    (httpx.ReadError, "unknown", False),
    (httpx.WriteError, "unknown", False),
    (httpx.RemoteProtocolError, "unknown", False),
])
async def test_transport_failures_are_classified_without_automatic_replay(
    exception: type[httpx.TransportError], outcome: str, retryable: bool,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise exception("fixture failure", request=request)

    bridge = HttpWhatsAppBridge("http://fixture-bridge", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(BridgeSendError) as raised:
            await bridge.send_text(recipient="fixture@c.us", text="intro", operation_id="op-1")
    finally:
        await bridge.close()
    assert raised.value.outcome == outcome
    assert raised.value.retryable is retryable
    assert calls == 1


@pytest.mark.parametrize(("status", "body", "outcome", "retryable", "session"), [
    (503, {"error": "Not ready", "code": "NOT_READY", "retryable": True,
           "outcome": "not_started"}, "not_started", True, True),
    (409, {"error": "Incomplete journal", "code": "OPERATION_UNKNOWN", "retryable": False,
           "outcome": "unknown"}, "unknown", False, False),
    (409, {"error": "Generation changed", "code": "GENERATION_MISMATCH", "retryable": True,
           "outcome": "not_started"}, "not_started", True, True),
    (400, {"error": "Invalid path", "code": "INVALID_PATH", "retryable": False,
           "outcome": "not_started"}, "not_started", False, False),
    (502, {"error": "Possible send", "code": "UNKNOWN", "retryable": True,
           "outcome": "unknown"}, "unknown", True, False),
    (503, {"error": "Unclassified"}, "unknown", False, False),
    (502, {"error": "Malformed", "code": "BROKEN", "retryable": "true",
           "outcome": "not_started"}, "unknown", False, False),
    (502, {"error": "Malformed", "code": "BROKEN", "retryable": True,
           "outcome": []}, "unknown", False, False),
    (504, "Gateway timeout", "unknown", False, False),
])
async def test_error_json_requires_an_explicit_valid_outcome(
    status: int, body: Any, outcome: str, retryable: bool, session: bool,
) -> None:
    bridge = HttpWhatsAppBridge("http://fixture-bridge", transport=httpx.MockTransport(
        lambda request: httpx.Response(status, json=body),
    ))
    try:
        with pytest.raises(BridgeSendError) as raised:
            await bridge.send_document(
                recipient="fixture@c.us", file_path=Path("fixture.pdf"), message=None,
                operation_id="pdf-1",
            )
    finally:
        await bridge.close()
    assert raised.value.outcome == outcome
    assert raised.value.retryable is retryable
    assert raised.value.session_unavailable is session


@pytest.mark.parametrize("body", [
    None, {}, {"status": "sent"},
    {"status": "sent", "operation_id": "different", "message_id": "message-1"},
    {"status": "sent", "operation_id": "pdf-1", "message_id": " "},
    {"status": "delivered", "operation_id": "pdf-1", "message_id": "message-1"},
])
async def test_malformed_success_receipts_are_unknown(body: Any) -> None:
    bridge = HttpWhatsAppBridge("http://fixture-bridge", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=body),
    ))
    try:
        with pytest.raises(BridgeSendError) as raised:
            await bridge.send_document(
                recipient="fixture@c.us", file_path=Path("fixture.pdf"), message=None,
                operation_id="pdf-1",
            )
    finally:
        await bridge.close()
    assert raised.value.code == "INVALID_SEND_RECEIPT"
    assert raised.value.outcome == "unknown"
    assert raised.value.retryable is False
