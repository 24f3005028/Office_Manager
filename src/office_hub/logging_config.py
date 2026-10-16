"""Console and rotating-file logging."""

from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler

from .config import Settings


def configure_logging(settings: Settings) -> None:
    """Configure process logging once, without logging secrets or file contents."""

    root = logging.getLogger()
    if root.handlers:
        return

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(threadName)s - %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = TimedRotatingFileHandler(
        settings.log_dir / "office_hub.log",
        when="midnight",
        backupCount=settings.log_retention_days,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    root.setLevel(logging.INFO)
