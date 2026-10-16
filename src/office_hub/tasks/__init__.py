"""Automation task registry.

Tasks are deliberately small adapters. They receive a context and return JSON-serializable
results, so the worker can persist outcomes without coupling the web layer to desktop libraries.
"""

from __future__ import annotations

from collections.abc import Mapping

from .base import AutomationTask
from .busy_exporter import BusyExporter
from .gsheets_sync import GoogleSheetsSync
from .whatsapp_sender import WhatsAppPdfSender

_TASKS: dict[str, AutomationTask] = {
    task.name: task for task in (WhatsAppPdfSender(), BusyExporter(), GoogleSheetsSync())
}


def get_task(name: str) -> AutomationTask | None:
    return _TASKS.get(name)


def available_tasks() -> Mapping[str, AutomationTask]:
    return _TASKS
