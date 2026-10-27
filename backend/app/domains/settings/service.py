"""Persistent workspace settings and document-root validation."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.db import Database

DOCUMENT_CATEGORIES = ("bills", "credit_notes", "debit_notes")


def _now() -> str:
    return datetime.now(UTC).isoformat()


class WorkspaceSettingsService:
    """Stores settings in SQLite and supplies roots to the document scanner."""

    def __init__(self, database: Database, defaults: Mapping[str, Sequence[Path]]) -> None:
        self.database = database
        self._seed_defaults(defaults)

    def get(self) -> dict[str, object]:
        roots = self._read_roots()
        category_status = {
            category: {
                "configured": bool(values),
                "valid_roots": sum(Path(value).expanduser().is_dir() for value in values),
                "total_roots": len(values),
            }
            for category, values in roots.items()
        }
        return {
            "document_roots": roots,
            "category_status": category_status,
            "configured": all(
                item["configured"] and item["valid_roots"] == item["total_roots"]
                for item in category_status.values()
            ),
        }

    def root_paths(self) -> dict[str, tuple[Path, ...]]:
        return {
            category: tuple(Path(value).expanduser() for value in values)
            for category, values in self._read_roots().items()
        }

    def update(self, document_roots: Mapping[str, Sequence[str]]) -> dict[str, object]:
        normalized: dict[str, list[str]] = {}
        for category in DOCUMENT_CATEGORIES:
            values = document_roots.get(category, ())
            if isinstance(values, (str, bytes)):
                raise ValueError(f"{category} folders must be a list")
            normalized_values: list[str] = []
            for raw_value in values:
                value = str(raw_value).strip()
                if not value:
                    continue
                path = Path(value).expanduser()
                if not path.is_dir():
                    raise ValueError(f"Folder does not exist or is not a directory: {value}")
                resolved = str(path.resolve())
                if resolved not in normalized_values:
                    normalized_values.append(resolved)
            normalized[category] = normalized_values

        connection = self.database.connect()
        try:
            with connection:
                connection.execute(
                    "INSERT INTO workspace_settings (id, document_roots, updated_at) "
                    "VALUES (1, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET document_roots = excluded.document_roots, "
                    "updated_at = excluded.updated_at",
                    (json.dumps(normalized), _now()),
                )
        finally:
            connection.close()
        return self.get()

    def _seed_defaults(self, defaults: Mapping[str, Sequence[Path]]) -> None:
        existing = self._read_roots_or_none()
        if existing is not None:
            return
        roots = {
            category: [str(Path(value).expanduser()) for value in defaults.get(category, ())]
            for category in DOCUMENT_CATEGORIES
        }
        connection = self.database.connect()
        try:
            with connection:
                connection.execute(
                    "INSERT INTO workspace_settings (id, document_roots, updated_at) "
                    "VALUES (1, ?, ?)",
                    (json.dumps(roots), _now()),
                )
        finally:
            connection.close()

    def _read_roots(self) -> dict[str, list[str]]:
        raw = self._read_roots_or_none() or {}
        return {
            category: [str(value) for value in raw.get(category, []) if str(value).strip()]
            for category in DOCUMENT_CATEGORIES
        }

    def _read_roots_or_none(self) -> dict[str, Any] | None:
        connection = self.database.connect()
        try:
            row = connection.execute(
                "SELECT document_roots FROM workspace_settings WHERE id = 1"
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        try:
            decoded = json.loads(str(row["document_roots"]))
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
