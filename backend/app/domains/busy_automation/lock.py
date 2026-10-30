"""Cross-platform desktop lock and Windows user-idle guard."""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.domains.busy_automation.errors import (
    BusyLockTimeoutError,
    BusyUserActiveError,
)

logger = logging.getLogger(__name__)


def _try_lock(fd: int) -> bool:
    if sys.platform == "win32":
        import msvcrt

        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def acquire_busy_lock(lock_path: Path, timeout: float) -> Iterator[None]:
    """Hold an exclusive OS file lock for the duration of a UI automation job."""

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    locked = False
    try:
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"0")
        deadline = time.monotonic() + timeout
        while not locked:
            locked = _try_lock(fd)
            if locked:
                break
            if time.monotonic() >= deadline:
                raise BusyLockTimeoutError(
                    f"BUSY automation is already running; waited {timeout:.0f}s "
                    f"for {lock_path.name}."
                )
            time.sleep(0.1)
        yield
    finally:
        if locked:
            try:
                _unlock(fd)
            except OSError as exc:
                logger.warning("Could not release BUSY automation lock: %s", exc)
        os.close(fd)


def _windows_idle_seconds() -> float | None:
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return None

    class _LastInputInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_uint),
            ("dwTime", ctypes.c_ulong),
        ]

    info = _LastInputInfo()
    info.cbSize = ctypes.sizeof(_LastInputInfo)
    try:
        if not windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        tick_count = int(windll.kernel32.GetTickCount())
        elapsed = (tick_count - int(info.dwTime)) & 0xFFFFFFFF
        return elapsed / 1000.0
    except (AttributeError, OSError, ValueError):
        return None


def wait_for_user_idle(
    min_idle_seconds: float,
    *,
    timeout: float,
    poll_interval: float = 0.25,
) -> None:
    """Wait until the desktop has been idle, or fail rather than steal focus."""

    if sys.platform != "win32" or min_idle_seconds <= 0:
        return

    deadline = time.monotonic() + timeout
    while True:
        idle = _windows_idle_seconds()
        if idle is None or idle >= min_idle_seconds:
            return
        if time.monotonic() >= deadline:
            raise BusyUserActiveError(
                "The desktop is still in active use; BUSY automation was not started."
            )
        time.sleep(poll_interval)
