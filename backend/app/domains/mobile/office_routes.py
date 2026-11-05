"""Explicit mobile office routes; no generic proxy or administrative endpoints."""

from __future__ import annotations

import json
from datetime import date
from typing import Annotated, Any, Literal
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field


class OfficePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=8, max_length=100, pattern=r"^[a-zA-Z0-9-]+$")
    confirmed: Literal[True]


class SyncPayload(OfficePayload):
    start_date: date | None = None
    end_date: date
    preview_only: bool = True


class SendPayload(OfficePayload):
    file_ids: list[Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]] = Field(
        min_length=1, max_length=500
    )
    recipient: str = Field(min_length=1, max_length=200)
    message: str | None = Field(default=None, max_length=4096)


class ReviewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: Literal[True]
    operation: Literal["verify", "release"]


def install_office_routes(app: FastAPI, authenticate: Any) -> None:
    current_user = Depends(authenticate)

    def tools(request: Request) -> Any:
        return request.app.state.mobile.office

    def failed(exc: ValueError) -> HTTPException:
        return HTTPException(409, str(exc))

    @app.get("/mobile/v1/office/pouncha")
    async def pouncha(request: Request, current: dict[str, Any] = current_user) -> Any:
        try:
            return await tools(request).call("/pouncha-sync/status")
        except ValueError as exc:
            raise failed(exc) from exc

    @app.get("/mobile/v1/office/whatsapp")
    async def whatsapp(request: Request, current: dict[str, Any] = current_user) -> Any:
        try:
            result = await tools(request).call("/whatsapp/status")
            return {
                key: result.get(key)
                for key in ("status", "connected", "message", "queue_wait_reason")
            }
        except ValueError as exc:
            raise failed(exc) from exc

    @app.get("/mobile/v1/office/contacts")
    async def contacts(
        request: Request,
        q: str = Query(default="", max_length=100),
        current: dict[str, Any] = current_user,
    ) -> Any:
        try:
            return await tools(request).contacts(q)
        except ValueError as exc:
            raise failed(exc) from exc

    @app.get("/mobile/v1/office/documents")
    async def documents(
        request: Request,
        start_date: date,
        end_date: date,
        category: Literal["bills", "credit_notes", "debit_notes", "all"] = "bills",
        current: dict[str, Any] = current_user,
    ) -> Any:
        if start_date > end_date:
            raise HTTPException(400, "Start date must be on or before end date.")
        params = {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()}
        if category != "all":
            params["category"] = category
        try:
            rows = await tools(request).call("/documents?" + urlencode(params))
            return [
                {
                    key: row.get(key)
                    for key in (
                        "file_id",
                        "file_name",
                        "category",
                        "effective_date",
                        "date_source",
                        "match_status",
                        "matched_voucher_no",
                    )
                }
                for row in rows
            ]
        except ValueError as exc:
            raise failed(exc) from exc

    @app.post("/mobile/v1/office/pouncha", status_code=202)
    async def sync(
        payload: SyncPayload, request: Request, current: dict[str, Any] = current_user
    ) -> Any:
        try:
            return await tools(request).create(
                current["id"],
                payload.request_key,
                "pouncha",
                {
                    "start_date": payload.start_date.isoformat() if payload.start_date else None,
                    "end_date": payload.end_date.isoformat(),
                    "preview_only": payload.preview_only,
                },
            )
        except ValueError as exc:
            raise failed(exc) from exc

    @app.post("/mobile/v1/office/send", status_code=202)
    async def send(
        payload: SendPayload, request: Request, current: dict[str, Any] = current_user
    ) -> Any:
        try:
            return await tools(request).create(
                current["id"],
                payload.request_key,
                "send",
                {
                    "file_ids": payload.file_ids,
                    "recipient": payload.recipient,
                    "message": payload.message,
                },
            )
        except ValueError as exc:
            raise failed(exc) from exc

    @app.get("/mobile/v1/office/actions")
    def actions(request: Request, current: dict[str, Any] = current_user) -> Any:
        return [
            {
                "id": row["id"],
                "kind": row["kind"],
                "state": row["status"],
                "created_at": row["created_at"],
                "result": json.loads(row["response"]) if row["response"] else {},
            }
            for row in request.app.state.mobile.store.office_actions(current["id"])
        ]

    @app.get("/mobile/v1/office/actions/{action_id}")
    async def action(
        action_id: str, request: Request, current: dict[str, Any] = current_user
    ) -> Any:
        try:
            return await tools(request).get(current["id"], action_id)
        except ValueError as exc:
            raise failed(exc) from exc

    @app.post("/mobile/v1/office/actions/{action_id}/cancel")
    async def cancel(
        action_id: str, request: Request, current: dict[str, Any] = current_user
    ) -> Any:
        try:
            return await tools(request).cancel(current["id"], action_id)
        except ValueError as exc:
            raise failed(exc) from exc

    @app.post("/mobile/v1/office/actions/{action_id}/review")
    async def review(
        action_id: str,
        payload: ReviewPayload,
        request: Request,
        current: dict[str, Any] = current_user,
    ) -> Any:
        try:
            return await tools(request).review(current["id"], action_id, payload.operation)
        except ValueError as exc:
            raise failed(exc) from exc
