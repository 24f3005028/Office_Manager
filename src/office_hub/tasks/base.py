"""Task contracts shared by all automation adapters."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from ..config import Settings


@dataclass(frozen=True)
class TaskContext:
    settings: Settings
    job_id: str
    dry_run: bool
    logger: logging.Logger

    def info(self, message: str) -> None:
        self.logger.info("job_id=%s %s", self.job_id, message)


@dataclass(frozen=True)
class TaskResult:
    summary: str
    data: dict[str, Any]


class AutomationTask(Protocol):
    name: str
    display_name: str

    def execute(self, payload: dict[str, Any], context: TaskContext) -> TaskResult:
        """Execute the task, or return a dry-run plan."""
