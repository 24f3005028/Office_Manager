from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


async def _proxy(request: Request, operation: str) -> Any:
    try:
        return await getattr(request.app.state.bridge, operation)()
    except Exception as exc:
        raise HTTPException(status_code=502, detail="WhatsApp bridge unavailable") from exc


@router.get("/status")
async def whatsapp_status(request: Request) -> Any:
    return await request.app.state.bridge_readiness.refresh()


@router.post("/start")
async def whatsapp_start(request: Request) -> Any:
    request.app.state.bridge_readiness.invalidate()
    result = await _proxy(request, "start")
    return request.app.state.bridge_readiness.observe_status(result)


@router.post("/reconnect")
async def whatsapp_reconnect(request: Request) -> Any:
    request.app.state.bridge_readiness.invalidate()
    result = await _proxy(request, "reconnect")
    return request.app.state.bridge_readiness.observe_status(result)


@router.get("/contacts")
async def whatsapp_contacts(request: Request) -> Any:
    return await _proxy(request, "contacts")


@router.get("/qr")
async def whatsapp_qr(request: Request) -> Response:
    try:
        content, media_type = await request.app.state.bridge.qr()
    except Exception as exc:
        raise HTTPException(status_code=502, detail="WhatsApp bridge unavailable") from exc
    return Response(content=content, media_type=media_type)
