"""Small filesystem helpers shared by the automation pipeline."""

from __future__ import annotations

import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def delete_file_with_retries(
    path: Path, *, retries: int = 5, delay_sec: float = 0.3
) -> bool:
    """Delete an ephemeral workbook, tolerating a brief Excel/Windows lock."""

    for attempt in range(retries):
        try:
            path.unlink(missing_ok=True)
            return True
        except OSError as exc:
            if attempt == retries - 1:
                logger.warning(
                    "Could not delete temporary BUSY export %s after %s attempts: %s",
                    path,
                    retries,
                    exc,
                )
                return False
            time.sleep(delay_sec)
    return False
