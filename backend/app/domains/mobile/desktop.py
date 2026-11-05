"""Cross-process BUSY exclusion and an interactive five-second office warning."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from app.domains.pouncha_sync.parser import SyncError


@contextmanager
def desktop_lock(database_path: Path) -> Iterator[None]:
    path = database_path.parent / "busy-desktop.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    stream: BinaryIO = path.open("a+b")
    locked = False
    try:
        stream.seek(0, os.SEEK_END)
        if not stream.tell():
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise SyncError(
                "BUSY is handling another request. Try again when it finishes."
            ) from exc
        locked = True
        yield
    finally:
        if locked:
            stream.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream, fcntl.LOCK_UN)
        stream.close()


def office_warning() -> bool:
    """No UI automation starts if the warning cannot be displayed successfully."""
    if sys.platform != "win32":
        raise SyncError("Fresh reports require the unlocked Windows office computer.")
    script = Path(__file__).resolve().parents[3] / "scripts" / "busy-mobile-warning.ps1"
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-STA",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
            ],
            capture_output=True,
            timeout=30,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SyncError("The office warning could not be shown. BUSY was left untouched.") from exc
    if result.returncode not in (0, 2):
        raise SyncError("Unlock the office desktop. The warning could not be shown.")
    return result.returncode == 0
