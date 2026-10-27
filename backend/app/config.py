"""Application settings loaded from environment variables and an optional .env file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_BILLS_ROOTS = (r"E:\BILL LDH 2026-27", r"E:\BILL PDF 2026-27")
DEFAULT_CREDIT_NOTE_ROOTS = (r"E:\C N 26-27", r"E:\C N 2026-27 LDH")
DEFAULT_DEBIT_NOTE_ROOTS = (r"E:\DEBIT NOTE 26-27", r"E:\DEBIT NOTE 26-27 LDH")


def _value_as_text(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        return "|".join(str(item) for item in value)
    return str(value)


def _split_values(value: str) -> tuple[str, ...]:
    text = value.strip()
    if not text:
        return ()
    if text.startswith("["):
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, list):
            return tuple(str(item).strip() for item in decoded if str(item).strip())
    return tuple(item.strip() for item in text.replace(";", "|").split("|") if item.strip())


class Settings(BaseSettings):
    """Runtime configuration for the API and its local integrations."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    bills_roots: str = Field(default="|".join(DEFAULT_BILLS_ROOTS), validation_alias="BILLS_ROOTS")
    credit_notes_roots: str = Field(
        default="|".join(DEFAULT_CREDIT_NOTE_ROOTS), validation_alias="CREDIT_NOTES_ROOTS"
    )
    debit_notes_roots: str = Field(
        default="|".join(DEFAULT_DEBIT_NOTE_ROOTS), validation_alias="DEBIT_NOTES_ROOTS"
    )
    database_path: Path = Field(
        default_factory=lambda: BACKEND_DIR / "data" / "dashboard.sqlite3",
        validation_alias="DATABASE_PATH",
    )
    whatsapp_bridge_url: str = Field(
        default="http://127.0.0.1:3001", validation_alias="WHATSAPP_BRIDGE_URL"
    )
    bridge_timeout_seconds: float = Field(
        default=30.0, gt=0, validation_alias="BRIDGE_TIMEOUT_SECONDS"
    )
    whatsapp_bridge_api_key: str | None = Field(
        default=None, validation_alias="WHATSAPP_BRIDGE_API_KEY"
    )
    worker_poll_seconds: float = Field(default=0.5, gt=0, validation_alias="WORKER_POLL_SECONDS")
    cors_origins: str = Field(
        default="http://localhost:3000|http://127.0.0.1:3000", validation_alias="CORS_ORIGINS"
    )

    @field_validator(
        "bills_roots", "credit_notes_roots", "debit_notes_roots", "cors_origins", mode="before"
    )
    @classmethod
    def normalize_list_settings(cls, value: Any) -> str:
        return _value_as_text(value)

    def roots_for(self, category: str) -> tuple[Path, ...]:
        values = {
            "bills": self.bills_roots,
            "credit_notes": self.credit_notes_roots,
            "debit_notes": self.debit_notes_roots,
        }
        try:
            raw_roots = values[category]
        except KeyError as exc:
            raise ValueError(f"Unknown document category: {category}") from exc
        return tuple(Path(item).expanduser() for item in _split_values(raw_roots))

    @property
    def cors_origin_list(self) -> list[str]:
        return list(_split_values(self.cors_origins))
