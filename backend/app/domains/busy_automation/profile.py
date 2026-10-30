"""Configurable BUSY 21 UI profile.

The profile keeps menu keys, dialog selectors and timing out of Python code so
a different BUSY build can be calibrated without editing the automation logic.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domains.busy_automation.errors import BusyAutomationError

logger = logging.getLogger(__name__)


class BusyRecipeProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = "Sales Register"
    navigation_keys: list[str] = Field(default_factory=list)
    navigation_titles: list[str] = Field(default_factory=list)
    modal_titles: list[str] = Field(default_factory=list)
    modal_keys: list[str] = Field(default_factory=list)
    series_keys: str | None = None
    series_value_keys: str | None = None
    series_control: dict[str, Any] | None = None
    start_date_focus_keys: str | None = None
    end_date_focus_keys: str | None = None
    start_date_control: dict[str, Any] | None = None
    end_date_control: dict[str, Any] | None = None
    date_format: str = "%d-%m-%Y"
    date_commit_keys: str = "{TAB}"
    load_keys: str = "{F2}"
    load_wait_sec: float = 1.5
    wait_timeout_sec: float = 10.0
    ready_title_re: str | None = None
    calibrated: bool = True


class AccountLedgerProfile(BusyRecipeProfile):
    """The BUSY 21 Rel 14.2 Account Ledger filter form.

    ``calibrated`` is deliberately false in the shipped JSON template. The
    pipeline refuses to run until a live calibration has filled in the actual
    focus keys or control selectors.
    """

    name: str = "Account Ledger - Sales"
    format_name: str | None = "BAGS"
    format_name_control: dict[str, Any] | None = None
    format_name_focus_keys: str | None = None
    account_name: str | None = "Sales"
    account_control: dict[str, Any] | None = None
    account_focus_keys: str | None = None
    optional_fields_control: dict[str, Any] | None = None
    optional_fields_focus_keys: str | None = None
    optional_fields_value: bool = True
    bill_references_control: dict[str, Any] | None = None
    bill_references_focus_keys: str | None = None
    bill_references_value: bool = True
    calibrated: bool = False


class BusyExportProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hotkey: str = "%e"
    dialog_title_re: str = r".*(Export Report Data|Export|Save As).*"
    format_control: dict[str, Any] | None = None
    format_value: str = "Microsoft Excel"
    format_keys: str = ""
    path_focus_keys: str | None = None
    path_control: dict[str, Any] | None = None
    auto_detect_path_control: bool = True
    append_extension: bool = False
    open_after_keys: str | None = "n"
    open_after_control: dict[str, Any] | None = None
    open_after_dialog_title_re: str | None = r"(?i).*(open|view).*(file|export|after).*"
    auto_detect_open_after_control: bool = True
    confirm_keys: str = "{ENTER}"
    success_title_re: str = (
        r"(?i).*(export completed|export successful|data exported|"
        r"saved successfully|export saved|export complete).*"
    )
    success_dismiss_keys: str = "{ENTER}"
    dialog_wait_sec: float = 1.5
    file_ready_timeout_sec: float = 20.0
    file_stable_sec: float = 0.6


class BusyUiProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key_pause_sec: float = 0.25
    dialog_wait_sec: float = 1.5
    exit_dialog_re: str = r".*(Quit|Close Company|Exit BUSY|Are you sure).*"
    exit_no_keys: str = "n"
    unsafe_dialog_re: str = (
        r".*(Save changes|Discard changes|Overwrite|Replace existing).*"
    )
    allowed_dialog_title_res: list[str] = Field(default_factory=list)
    allowed_dialog_dismiss_keys: str = "{ENTER}"
    sales_register: BusyRecipeProfile = Field(default_factory=BusyRecipeProfile)
    account_ledger_sales: AccountLedgerProfile = Field(
        default_factory=AccountLedgerProfile
    )
    account_ledger_sales_return: AccountLedgerProfile = Field(
        default_factory=lambda: AccountLedgerProfile(
            name="Account Ledger - Sales Return", account_name="Sales Return"
        )
    )
    purchase_return: AccountLedgerProfile = Field(
        default_factory=lambda: AccountLedgerProfile(
            name="Purchase Return", account_name="Purchase Return"
        )
    )
    export: BusyExportProfile = Field(default_factory=BusyExportProfile)


def load_profile(path: Path | None) -> BusyUiProfile:
    """Load a profile file, or return defaults when it does not exist."""

    if path is None or not path.is_file():
        return BusyUiProfile()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return BusyUiProfile.model_validate(raw)
    except (OSError, ValueError) as exc:
        raise BusyAutomationError(
            f"Could not load the BUSY UI profile at {path}: {exc}"
        ) from exc
