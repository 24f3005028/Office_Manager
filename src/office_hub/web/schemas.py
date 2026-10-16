"""Validated API request and response shapes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class JobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_name: str = Field(min_length=1, max_length=100)
    payload: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = True


class TaskSummary(BaseModel):
    name: str
    display_name: str


class WhatsAppInboundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_message_id: str = Field(min_length=1, max_length=200)
    sender_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=4000)
    received_at: datetime | None = None
    input_file: str | None = Field(default=None, max_length=500)
