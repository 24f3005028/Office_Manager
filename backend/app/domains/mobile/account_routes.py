"""Authenticated account catalogue and manually requested account reports."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.domains.mobile.account_reports import financial_year, india_today


class LedgerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    start_date: date
    end_date: date
    request_key: str = Field(min_length=8, max_length=100, pattern=r"^[a-zA-Z0-9-]+$")


class GroupBalanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    as_of: date
    request_key: str = Field(min_length=8, max_length=100, pattern=r"^[a-zA-Z0-9-]+$")


def install_account_routes(app: FastAPI, authenticate: Any) -> None:
    current_user = Depends(authenticate)

    @app.get("/mobile/v1/account-reports/options")
    def options(current: dict[str, Any] = current_user) -> dict[str, str]:
        today = india_today()
        fy, start, _ = financial_year(today)
        return {"financial_year": fy, "start_date": start.isoformat(), "as_of": today.isoformat()}

    @app.get("/mobile/v1/account-groups")
    def groups(
        request: Request,
        current: dict[str, Any] = current_user,
        q: str = Query(default="", max_length=100),
    ) -> Any:
        return request.app.state.mobile.accounts.groups(q)

    @app.get("/mobile/v1/accounts")
    def accounts(
        request: Request,
        current: dict[str, Any] = current_user,
        q: str = Query(default="", max_length=100),
        group_id: str | None = Query(default=None, pattern=r"^[a-f0-9]{32}$"),
    ) -> Any:
        return request.app.state.mobile.accounts.accounts(q, group_id)

    @app.get("/mobile/v1/account-reports")
    def history(
        request: Request,
        current: dict[str, Any] = current_user,
        kind: Literal["ledger", "group_balances"] = "ledger",
    ) -> Any:
        return request.app.state.mobile.store.jobs(current["id"], kind)

    @app.post("/mobile/v1/account-reports/ledger", status_code=202)
    def ledger(
        payload: LedgerRequest, request: Request, current: dict[str, Any] = current_user
    ) -> Any:
        try:
            return request.app.state.mobile.submit_account(
                current["id"],
                payload.account_id,
                "ledger",
                payload.end_date,
                payload.request_key,
                payload.start_date,
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/mobile/v1/account-reports/group-balances", status_code=202)
    def balances(
        payload: GroupBalanceRequest, request: Request, current: dict[str, Any] = current_user
    ) -> Any:
        try:
            return request.app.state.mobile.submit_account(
                current["id"],
                payload.group_id,
                "group_balances",
                payload.as_of,
                payload.request_key,
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/mobile/v1/reports/{job_id}/balances")
    def rows(job_id: str, request: Request, current: dict[str, Any] = current_user) -> Any:
        try:
            return request.app.state.mobile.balance_data(current["id"], job_id)
        except (OSError, ValueError) as exc:
            raise HTTPException(
                404, "Group balances unavailable or expired. Request a fresh report."
            ) from exc
