"""SQLAlchemy engine and session management."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    """Base class for all persisted models."""


class Database:
    """Own an engine and a session factory for one application process."""

    def __init__(self, url: str) -> None:
        engine_kwargs: dict[str, object] = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            engine_kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            engine_kwargs["poolclass"] = StaticPool

        self.engine: Engine = create_engine(url, **engine_kwargs)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
        )

    def create_schema(self) -> None:
        """Create missing tables for a first local run.

        Versioned deployments should still run ``alembic upgrade head``. Keeping this fallback
        makes the executable usable immediately after bootstrap on a new workstation.
        """

        from . import models  # noqa: F401  # Register model metadata before create_all.

        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Yield a session and always close it."""

        with self.session_factory() as session:
            yield session

    def dispose(self) -> None:
        self.engine.dispose()
