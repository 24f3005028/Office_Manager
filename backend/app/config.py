"""Application settings loaded from environment variables and an optional .env file."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_BILLS_ROOTS = (r"E:\BILL LDH 2026-27", r"E:\BILL PDF 2026-27")
DEFAULT_CREDIT_NOTE_ROOTS = (r"E:\C N 26-27", r"E:\C N 2026-27 LDH")
DEFAULT_DEBIT_NOTE_ROOTS = (r"E:\DEBIT NOTE 26-27", r"E:\DEBIT NOTE 26-27 LDH")
DEFAULT_IGNORED_DIRECTORIES = "BusyWin|EInvoiceTemp|EWayBillTemp|SYSTEM|XMPPMessages"
DEFAULT_SERIES_ALIASES = '{"HSTL": "HSL", "HSL": "HSL", "HST": "HST", "CN": "CN", "DN": "DN"}'


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


def _parse_alias_map(value: str) -> dict[str, str]:
    text = value.strip()
    if not text:
        return {}
    if text.startswith("{"):
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("BUSY series aliases must be valid JSON or KEY:VALUE pairs") from exc
        if not isinstance(decoded, dict):
            raise ValueError("BUSY series aliases must be an object")
        return {
            str(key).strip().upper(): str(alias).strip().upper()
            for key, alias in decoded.items()
            if str(key).strip() and str(alias).strip()
        }
    aliases: dict[str, str] = {}
    for item in text.replace(";", "|").split("|"):
        if not item.strip():
            continue
        separator = ":" if ":" in item else "="
        if separator not in item:
            raise ValueError(f"Invalid BUSY series alias: {item}")
        key, alias = item.split(separator, 1)
        if key.strip() and alias.strip():
            aliases[key.strip().upper()] = alias.strip().upper()
    return aliases


class Settings(BaseSettings):
    """Runtime configuration for the API and its local integrations."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
        env_ignore_empty=True,
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
    busy_inbox_dir: Path = Field(
        default_factory=lambda: BACKEND_DIR / "data" / "busy_inbox",
        validation_alias="BUSY_INBOX_DIR",
    )
    busy_ignored_directories: str = Field(
        default=DEFAULT_IGNORED_DIRECTORIES, validation_alias="BUSY_IGNORED_DIRECTORIES"
    )
    busy_series_aliases: str = Field(
        default=DEFAULT_SERIES_ALIASES, validation_alias="BUSY_SERIES_ALIASES"
    )
    busy_financial_year: str = Field(default="26-27", validation_alias="BUSY_FINANCIAL_YEAR")
    pdf_date_extraction: bool = Field(
        default=True, validation_alias="PDF_DATE_EXTRACTION"
    )
    pdf_date_min_date: date | None = Field(
        default=None, validation_alias="PDF_DATE_MIN_DATE"
    )
    pdf_date_max_date: date | None = Field(
        default=None, validation_alias="PDF_DATE_MAX_DATE"
    )
    busy_executable_path: Path = Field(
        default=Path(r"E:\C N 26-27\BusyWin\Busy21.exe"),
        validation_alias="BUSY_EXECUTABLE_PATH",
    )
    busy_window_title_re: str = Field(
        default=r".*BUSY.*", validation_alias="BUSY_WINDOW_TITLE_RE"
    )
    busy_expected_company_substring: str = Field(
        default="H.S. Traders", validation_alias="BUSY_EXPECTED_COMPANY_SUBSTRING"
    )
    busy_automation_timeout_seconds: float = Field(
        default=60.0, gt=0, validation_alias="BUSY_AUTOMATION_TIMEOUT_SECONDS"
    )
    busy_min_user_idle_seconds: float = Field(
        default=3.0, ge=0, validation_alias="BUSY_MIN_USER_IDLE_SECONDS"
    )
    busy_ui_profile_path: Path = Field(
        default_factory=lambda: BACKEND_DIR / "config" / "busy_ui_profile.json",
        validation_alias="BUSY_UI_PROFILE_PATH",
    )
    busy_lock_path: Path = Field(
        default_factory=lambda: BACKEND_DIR / "data" / "busy_automation.lock",
        validation_alias="BUSY_LOCK_PATH",
    )
    busy_automation_temp_dir: Path = Field(
        default_factory=lambda: BACKEND_DIR / "data" / "busy_automation",
        validation_alias="BUSY_AUTOMATION_TEMP_DIR",
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
        "bills_roots",
        "credit_notes_roots",
        "debit_notes_roots",
        "busy_ignored_directories",
        "busy_series_aliases",
        "cors_origins",
        mode="before",
    )
    @classmethod
    def normalize_list_settings(cls, value: Any) -> str:
        return _value_as_text(value)

    @field_validator("busy_financial_year", mode="before")
    @classmethod
    def normalize_financial_year(cls, value: Any) -> str:
        text = str(value).strip()
        return text or "26-27"

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
    def ignored_directory_names(self) -> frozenset[str]:
        return frozenset(
            item.casefold() for item in _split_values(self.busy_ignored_directories)
        )

    @property
    def series_alias_map(self) -> dict[str, str]:
        aliases = _parse_alias_map(self.busy_series_aliases)
        return aliases or _parse_alias_map(DEFAULT_SERIES_ALIASES)

    @property
    def cors_origin_list(self) -> list[str]:
        return list(_split_values(self.cors_origins))
