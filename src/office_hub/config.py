"""Application settings and runtime directory management."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_data_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "OfficeHub"
    return Path.home() / ".office_hub"


class Settings(BaseSettings):
    """Settings loaded from environment variables prefixed with ``OFFICE_HUB_``."""

    model_config = SettingsConfigDict(
        env_prefix="OFFICE_HUB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Office Hub"
    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)

    data_dir: Path = Field(default_factory=_default_data_dir)
    database_url: str | None = None
    billing_folder: Path = Field(default_factory=lambda: Path.home() / "OfficeHub" / "Billing")
    busy_exe_path: Path | None = None
    busy_ui_profile_file: Path | None = None
    busy_automation_enabled: bool = False
    busy_automation_timeout_seconds: int = Field(default=120, ge=10, le=900)
    output_dir: Path | None = None

    allow_external_actions: bool = False
    enable_worker: bool = True
    enable_scheduler: bool = True
    scheduled_whatsapp_enabled: bool = False
    scheduler_timezone: str = "Asia/Kolkata"
    worker_poll_seconds: float = Field(default=2.0, gt=0.1, le=60)
    log_retention_days: int = Field(default=14, ge=1, le=365)

    google_credentials_file: Path | None = None
    google_sheet_id: str | None = None

    whatsapp_provider: str = "dry_run"
    whatsapp_allowed_senders: str = ""
    whatsapp_cloud_access_token: SecretStr | None = None
    whatsapp_cloud_phone_number_id: str | None = None
    whatsapp_cloud_verify_token: SecretStr | None = None
    whatsapp_cloud_app_secret: SecretStr | None = None

    @property
    def whatsapp_sender_allowlist(self) -> frozenset[str]:
        return frozenset(
            sender.strip()
            for sender in self.whatsapp_allowed_senders.split(",")
            if sender.strip()
        )

    @property
    def resolved_database_url(self) -> str:
        """Return the configured URL or a SQLite URL inside the runtime directory."""

        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'office_hub.sqlite3').as_posix()}"

    @property
    def resolved_output_dir(self) -> Path:
        return self.output_dir or self.data_dir / "outputs"

    @property
    def busy_inbox_dir(self) -> Path:
        return self.resolved_output_dir / "busy-inbox"

    @property
    def busy_reports_dir(self) -> Path:
        return self.resolved_output_dir / "busy-reports"

    @property
    def busy_lock_file(self) -> Path:
        return self.data_dir / "busy-automation.lock"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    def ensure_runtime_dirs(self) -> None:
        """Create only application-owned runtime directories."""

        for directory in (
            self.data_dir,
            self.log_dir,
            self.resolved_output_dir,
            self.busy_inbox_dir,
            self.busy_reports_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance."""

    return Settings()
