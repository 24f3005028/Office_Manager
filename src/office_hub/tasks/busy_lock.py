"""A process-wide lock for BUSY desktop automation.

This lock coordinates Office Hub workers. It does not claim that a human is not using BUSY; the
UI adapter performs an additional foreground-window check and refuses to automate when BUSY is
the active application.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from types import TracebackType
from typing import BinaryIO


class BusyAutomationBusyError(RuntimeError):
    """Raised when another Office Hub process owns the BUSY automation lock."""


class BusyAutomationLock:
    """Cross-platform best-effort exclusive lock backed by a one-byte lock file."""

    def __init__(self, path: Path, timeout_seconds: float = 0) -> None:
        self.path = path
        self.timeout_seconds = timeout_seconds
        self._handle: BinaryIO | None = None

    def __enter__(self) -> BusyAutomationLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        deadline = time.monotonic() + max(0, self.timeout_seconds)
        while True:
            try:
                self._try_lock(handle)
                self._handle = handle
                return self
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    handle.close()
                    raise BusyAutomationBusyError("Another BUSY automation job is active") from None
                time.sleep(0.25)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._handle is None:
            return
        self._unlock(self._handle)
        self._handle.close()
        self._handle = None

    @staticmethod
    def _try_lock(handle: BinaryIO) -> None:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            handle.write(b"0")
            handle.flush()
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl = __import__("fcntl")

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock(handle: BinaryIO) -> None:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl = __import__("fcntl")

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
