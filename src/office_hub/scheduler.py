"""APScheduler integration for durable scheduled jobs."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore[import-untyped]

from .config import Settings
from .database import Database
from .repository import JobRepository

logger = logging.getLogger(__name__)


class JobScheduler:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings
        self._scheduler: BackgroundScheduler | None = None

    def start(self) -> None:
        if self._scheduler is not None:
            return
        scheduler = BackgroundScheduler(timezone=self.settings.scheduler_timezone)
        if self.settings.scheduled_whatsapp_enabled:
            scheduler.add_job(
                self.enqueue_midnight_whatsapp,
                trigger="cron",
                hour=0,
                minute=0,
                id="scheduled_whatsapp_pdf_sender",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            logger.info("Scheduled WhatsApp job at midnight (%s)", self.settings.scheduler_timezone)
        scheduler.start()
        self._scheduler = scheduler

    def stop(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None

    def enqueue_midnight_whatsapp(self) -> None:
        target_date = (
            datetime.now(ZoneInfo(self.settings.scheduler_timezone)).date() - timedelta(days=1)
        )
        with self.database.session_factory() as session:
            JobRepository(session).create(
                task_name="whatsapp_pdf_sender",
                payload={
                    "folder": str(self.settings.billing_folder),
                    "target_date": target_date.isoformat(),
                    "source": "scheduler",
                },
                dry_run=not self.settings.allow_external_actions,
            )
        logger.info("Queued scheduled WhatsApp job for %s", target_date.isoformat())
