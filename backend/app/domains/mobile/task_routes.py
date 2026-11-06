"""Authenticated task sharing; reminder reads never invoke desktop automation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

INDIA = timezone(timedelta(hours=5, minutes=30))


class TaskPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=160)
    notes: str = Field(default="", max_length=2000)
    due_at: datetime
    repeat_rule: Literal["none", "daily", "weekly", "monthly"] = "none"
    assignees: list[Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]] = Field(max_length=100)

    @field_validator("title")
    @classmethod
    def title_text(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("Enter a task title without control characters.")
        return value

    @field_validator("due_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or not 2020 <= value.year <= 2099:
            raise ValueError("Use a date with a timezone, between 2020 and 2099.")
        return value.astimezone(INDIA)

    def data(self) -> dict[str, Any]:
        return {**self.model_dump(), "due_at": self.due_at.isoformat()}


class CreateTask(TaskPayload):
    request_key: str = Field(min_length=8, max_length=100, pattern=r"^[a-zA-Z0-9-]+$")


class TaskVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)


class UpdateTask(TaskPayload):
    version: int = Field(ge=1)


def install_task_routes(app: FastAPI, authenticate: Any) -> None:
    current_user = Depends(authenticate)

    @app.get("/mobile/v1/tasks")
    def tasks(request: Request, current: dict[str, Any] = current_user) -> Any:
        return request.app.state.mobile.tasks.rows()

    @app.get("/mobile/v1/task-people")
    def people(request: Request, current: dict[str, Any] = current_user) -> Any:
        return request.app.state.mobile.tasks.people()

    @app.post("/mobile/v1/tasks", status_code=201)
    def create(
        payload: CreateTask, request: Request, current: dict[str, Any] = current_user
    ) -> Any:
        try:
            return request.app.state.mobile.tasks.create(current["id"], payload.data())
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    def change(
        request: Request,
        current: dict[str, Any],
        task_id: str,
        version: int,
        operation: str,
        data: dict[str, Any] | None = None,
    ) -> Any:
        service = request.app.state.mobile
        try:
            return service.tasks.change(
                task_id,
                current["id"],
                version,
                operation,
                manager=service.can_invite_users(current),
                payload=data,
            )
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/mobile/v1/tasks/{task_id}/complete")
    def complete(
        task_id: str, payload: TaskVersion, request: Request, current: dict[str, Any] = current_user
    ) -> Any:
        return change(request, current, task_id, payload.version, "complete")

    @app.post("/mobile/v1/tasks/{task_id}/cancel")
    def cancel(
        task_id: str, payload: TaskVersion, request: Request, current: dict[str, Any] = current_user
    ) -> Any:
        return change(request, current, task_id, payload.version, "cancel")

    @app.post("/mobile/v1/tasks/{task_id}/update")
    def update(
        task_id: str, payload: UpdateTask, request: Request, current: dict[str, Any] = current_user
    ) -> Any:
        return change(request, current, task_id, payload.version, "updated", payload.data())
