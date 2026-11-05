"""Loopback-only administration. Never mounted in the mobile gateway."""

from __future__ import annotations

from contextlib import closing
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from app.domains.mobile.accounts import account_names
from app.domains.mobile.store import MobileStore


def local_only(request: Request) -> None:
    if request.client is None or request.client.host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(403, "Manage mobile access on the office computer.")
    if request.url.hostname not in {"127.0.0.1", "localhost", "::1", "testserver"}:
        raise HTTPException(403, "Use the local office dashboard address.")
    origin = request.headers.get("origin")
    if origin and origin not in request.app.state.settings.cors_origin_list:
        raise HTTPException(403, "Browser origin is not allowed.")


router = APIRouter(prefix="/mobile-admin", dependencies=[Depends(local_only)])


class InviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100, pattern=r"^[^\x00-\x1f]+$")
    phone: str = Field(pattern=r"^[1-9]\d{7,14}$")


def store(request: Request) -> MobileStore:
    return request.app.state.mobile_store  # type: ignore[no-any-return]


@router.get("/status")
def status(request: Request) -> dict[str, Any]:
    current = store(request)
    with closing(current.database.connect()) as db:
        count = db.execute("SELECT COUNT(*) FROM mobile_parties").fetchone()[0]
    return {
        "users": current.users(),
        "party_count": count,
        "gateway_port": 8002,
        "manual_only": True,
    }


@router.post("/invites", status_code=201)
def invite(payload: InviteRequest, request: Request) -> dict[str, Any]:
    return store(request).invite(payload.name.strip(), payload.phone)


@router.post("/users/{user_id}/revoke")
def revoke(user_id: str, request: Request) -> dict[str, bool]:
    store(request).revoke(user_id)
    return {"revoked": True}


@router.post("/accounts")
async def accounts(request: Request, file: Annotated[UploadFile, File()]) -> dict[str, int]:
    content = await file.read(10 * 1024 * 1024 + 1)
    await file.close()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "Account export exceeds 10 MiB.")
    try:
        names = account_names(content)
    except Exception as exc:
        raise HTTPException(400, "Use the original BUSY List of Accounts .xlsx export.") from exc
    return {"added": store(request).add_parties(names), "trade_accounts": len(names)}
