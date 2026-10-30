"""Midnight IST scheduler and startup catch-up for Pouncha sync."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo

from app.domains.pouncha_sync.models import (
    PounchaSyncRun,
    PounchaTrigger,
)
from app.domains.pouncha_sync.service import PounchaSyncService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PounchaSchedulerStatus:
    enabled: bool
    running: bool
    timezone: str
    next_run_at: datetime | None
    waiting_for_busy: bool
    last_check_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None


def start_of_today(moment: datetime, timezone: tzinfo) -> datetime:
    local = moment.astimezone(timezone)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def next_midnight_after(moment: datetime, timezone: tzinfo) -> datetime:
    local = moment.astimezone(timezone)
    tomorrow = local + timedelta(days=1)
    return tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)


def should_catch_up(
    *,
    now: datetime,
    timezone: tzinfo,
    last_success: PounchaSyncRun | None,
    active_run: PounchaSyncRun | None,
    busy_available: bool,
) -> bool:
    """Return whether a catch-up run is needed right now."""

    if active_run is not None:
        return False
    if not busy_available:
        return False
    if last_success is not None and last_success.completed_at is not None:
        completed = last_success.completed_at
        if completed.tzinfo is None:
            completed = completed.replace(tzinfo=timezone)
        if completed >= start_of_today(now, timezone):
            return False
    return True


class PounchaSyncScheduler:
    def __init__(
        self,
        service: PounchaSyncService,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.service = service
        self._now = now or (lambda: datetime.now(service.timezone))
        self._interval = timedelta(
            minutes=service.settings.pouncha_catchup_interval_minutes
        )
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._running = False
        self._waiting_for_busy = False
        self._last_check_at: datetime | None = None
        self._last_error: str | None = None
        self._next_run_at: datetime | None = None

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._running = True
        now = self._now()
        self._next_run_at = next_midnight_after(now, self.service.timezone)
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        self._stop.set()
        task = self._task
        self._task = None
        if task is not None:
            with suppress(asyncio.CancelledError):
                await task

    async def _loop(self) -> None:
        try:
            await self._catch_up(self._now())
            while not self._stop.is_set():
                now = self._now()
                if self._next_run_at is None or now >= self._next_run_at:
                    await self._run_midnight(now)
                    self._next_run_at = next_midnight_after(
                        now, self.service.timezone
                    )
                if self._catch_up_due(now):
                    await self._catch_up(now)
                delay = self._seconds_until_next_event(now)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                except TimeoutError:
                    continue
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - defensive loop guard
            logger.exception("Pouncha scheduler stopped unexpectedly: %s", exc)
            self._last_error = str(exc)
        finally:
            self._running = False

    def _catch_up_due(self, now: datetime) -> bool:
        if self._last_check_at is None:
            return True
        return now - self._last_check_at >= self._interval

    def _seconds_until_next_event(self, now: datetime) -> float:
        targets: list[datetime] = []
        if self._next_run_at is not None:
            targets.append(self._next_run_at)
        if self._last_check_at is not None:
            targets.append(self._last_check_at + self._interval)
        if not targets:
            return 1.0
        target = min(targets)
        seconds = (target - now).total_seconds()
        return max(1.0, min(seconds, 3600.0))

    async def _run_midnight(self, now: datetime) -> None:
        self._last_check_at = now
        if not self.service.configured:
            return
        if self.service.repository.active_run() is not None:
            return
        if not self.service.busy_available():
            self._waiting_for_busy = True
            logger.info("Pouncha midnight sync is waiting for BUSY 21.")
            return
        self._waiting_for_busy = False
        try:
            await self.service.run_new_busy(
                trigger_type=PounchaTrigger.SCHEDULED_MIDNIGHT,
                skip_when_busy_closed=True,
            )
            self._last_error = None
        except Exception as exc:
            self._last_error = self._error_text(exc)
            logger.warning("Pouncha midnight sync failed: %s", exc)

    async def _catch_up(self, now: datetime) -> None:
        self._last_check_at = now
        if not self.service.configured:
            self._waiting_for_busy = False
            return
        if not self.service.busy_available():
            self._waiting_for_busy = True
            return
        self._waiting_for_busy = False
        midnight = start_of_today(now, self.service.timezone)
        last_success = self.service.repository.last_successful_since(midnight)
        if not should_catch_up(
            now=now,
            timezone=self.service.timezone,
            last_success=last_success,
            active_run=self.service.repository.active_run(),
            busy_available=True,
        ):
            return
        try:
            await self.service.run_new_busy(
                trigger_type=PounchaTrigger.STARTUP_CATCHUP,
                skip_when_busy_closed=True,
            )
            self._last_error = None
        except Exception as exc:
            self._last_error = self._error_text(exc)
            logger.warning("Pouncha catch-up sync failed: %s", exc)

    def status(self) -> PounchaSchedulerStatus:
        now = self._now()
        last_success = self.service.repository.last_success()
        return PounchaSchedulerStatus(
            enabled=self.service.settings.pouncha_sync_enabled,
            running=self._running,
            timezone=str(self.service.timezone),
            next_run_at=self._next_run_at
            or next_midnight_after(now, self.service.timezone),
            waiting_for_busy=self._waiting_for_busy,
            last_check_at=self._last_check_at,
            last_success_at=(
                last_success.completed_at if last_success is not None else None
            ),
            last_error=self._last_error,
        )

    @staticmethod
    def _error_text(exc: BaseException) -> str:
        text = str(exc).strip() or exc.__class__.__name__
        return text[:1000]
