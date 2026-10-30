"""BUSY report recipes.

The Account Ledger recipes follow the BUSY 21 Rel 14.2 screen flow used by
H.S. Traders. The shipped profile is intentionally uncalibrated: the pipeline
refuses to run until the live focus keys and control selectors have been filled
in with ``scripts/inspect_busy_ui.py``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from app.domains.busy_automation.errors import BusyAutomationError
from app.domains.busy_automation.profile import (
    AccountLedgerProfile,
    BusyRecipeProfile,
    BusyUiProfile,
)
from app.domains.busy_automation.session import BusySessionProtocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ReportRequest:
    start_date: date
    end_date: date
    series: str | None = None


class BusyReportRecipe(Protocol):
    category: str

    def open_report(
        self, session: BusySessionProtocol, request: ReportRequest
    ) -> None: ...


class SalesRegisterRecipe:
    """Navigate BUSY to the Sales Register and apply the requested date range."""

    category = "bills"

    def __init__(
        self,
        profile: BusyRecipeProfile,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.profile = profile
        self._sleep = sleep

    def open_report(
        self, session: BusySessionProtocol, request: ReportRequest
    ) -> None:
        profile = self.profile
        if not profile.navigation_keys:
            raise BusyAutomationError(
                "Sales Register navigation is not calibrated. Open BUSY, run "
                "scripts/inspect_busy_ui.py, and fill "
                "sales_register.navigation_keys in config/busy_ui_profile.json."
            )
        if request.start_date > request.end_date:
            raise ValueError("The report start date is after the end date.")

        session.focus()
        for index, keys in enumerate(profile.navigation_keys):
            session.send_keys(keys)
            if index < len(profile.navigation_titles):
                title_re = profile.navigation_titles[index]
                if title_re:
                    session.wait_for_title(
                        title_re, timeout=profile.wait_timeout_sec
                    )

        if request.series:
            self._set_series(session, request.series)
        self._set_date(
            session,
            control=profile.start_date_control,
            focus_keys=profile.start_date_focus_keys,
            value=request.start_date,
            field_name="start",
        )
        self._set_date(
            session,
            control=profile.end_date_control,
            focus_keys=profile.end_date_focus_keys,
            value=request.end_date,
            field_name="end",
        )

        if profile.load_keys:
            session.send_keys(profile.load_keys)
        if profile.ready_title_re:
            session.wait_for_title(
                profile.ready_title_re, timeout=profile.wait_timeout_sec
            )
        else:
            self._sleep(profile.load_wait_sec)

    def _set_series(
        self, session: BusySessionProtocol, series: str
    ) -> None:
        profile = self.profile
        if profile.series_control:
            if not session.set_text_anywhere(profile.series_control, series):
                raise BusyAutomationError(
                    "Could not fill the Sales Register series field."
                )
            return
        if profile.series_keys:
            session.send_keys(profile.series_keys)
        if profile.series_value_keys:
            session.type_text(profile.series_value_keys.format(series=series))
            return
        if not profile.series_keys:
            raise BusyAutomationError(
                "Sales Register series entry is not calibrated."
            )

    def _set_date(
        self,
        session: BusySessionProtocol,
        *,
        control: Mapping[str, object] | None,
        focus_keys: str | None,
        value: date,
        field_name: str,
    ) -> None:
        profile = self.profile
        text = value.strftime(profile.date_format)
        if control:
            if not session.set_text_anywhere(control, text):
                raise BusyAutomationError(
                    f"Could not set the Sales Register {field_name} date to {text}."
                )
        elif focus_keys:
            session.send_keys(focus_keys)
            session.send_keys("^a")
            session.send_keys(text)
        else:
            raise BusyAutomationError(
                "Sales Register date fields are not calibrated. Set "
                f"{field_name}_date_control or {field_name}_date_focus_keys "
                "in the UI profile."
            )
        if profile.date_commit_keys:
            session.send_keys(profile.date_commit_keys)


class AccountLedgerRecipe:
    """Open an Account Ledger report and apply its filter form.

    This recipe drives the BUSY 21 flow:

    ``navigation_keys`` -> optional modal confirmations -> Account Ledger form
    (format, account, dates, transport/bill-reference options) -> load keys.
    """

    category = "bills"

    def __init__(
        self,
        profile: AccountLedgerProfile,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.profile = profile
        self._sleep = sleep

    def open_report(
        self, session: BusySessionProtocol, request: ReportRequest
    ) -> None:
        profile = self.profile
        if not profile.calibrated:
            raise BusyAutomationError(
                f"{profile.name} is not calibrated. Open BUSY, run "
                "scripts/inspect_busy_ui.py --watch --controls, and fill the "
                "Account Ledger focus keys or controls in "
                "config/busy_ui_profile.json. Then set calibrated to true."
            )
        if not profile.navigation_keys:
            raise BusyAutomationError(
                f"{profile.name} navigation is not calibrated."
            )
        if request.start_date > request.end_date:
            raise ValueError("The report start date is after the end date.")

        session.focus()
        for index, keys in enumerate(profile.navigation_keys):
            session.send_keys(keys)
            if index < len(profile.navigation_titles):
                title_re = profile.navigation_titles[index]
                if title_re:
                    session.wait_for_title(
                        title_re, timeout=profile.wait_timeout_sec
                    )

        self._confirm_modals(session)

        if profile.format_name:
            self._set_text_field(
                session,
                label="Format Name",
                control=profile.format_name_control,
                focus_keys=profile.format_name_focus_keys,
                value=profile.format_name,
            )
        if profile.account_name:
            self._set_text_field(
                session,
                label="Select Account",
                control=profile.account_control,
                focus_keys=profile.account_focus_keys,
                value=profile.account_name,
            )

        self._set_date(
            session,
            control=profile.start_date_control,
            focus_keys=profile.start_date_focus_keys,
            value=request.start_date,
            field_name="Starting Date",
        )
        self._set_date(
            session,
            control=profile.end_date_control,
            focus_keys=profile.end_date_focus_keys,
            value=request.end_date,
            field_name="Ending Date",
        )

        self._set_option(
            session,
            label="Show Opt. Fields/Transport Details",
            control=profile.optional_fields_control,
            focus_keys=profile.optional_fields_focus_keys,
            value=profile.optional_fields_value,
        )
        self._set_option(
            session,
            label="Show Bill References",
            control=profile.bill_references_control,
            focus_keys=profile.bill_references_focus_keys,
            value=profile.bill_references_value,
        )

        if profile.load_keys:
            session.send_keys(profile.load_keys)
        if profile.ready_title_re:
            session.wait_for_title(
                profile.ready_title_re, timeout=profile.wait_timeout_sec
            )
        else:
            self._sleep(profile.load_wait_sec)

    def _confirm_modals(self, session: BusySessionProtocol) -> None:
        profile = self.profile
        for title, keys in zip(
            profile.modal_titles, profile.modal_keys, strict=False
        ):
            if title:
                session.wait_for_title(title, timeout=profile.wait_timeout_sec)
            if keys:
                session.send_keys(keys)

    def _set_text_field(
        self,
        session: BusySessionProtocol,
        *,
        label: str,
        control: Mapping[str, object] | None,
        focus_keys: str | None,
        value: str,
    ) -> None:
        if control:
            if not session.set_text_anywhere(control, value):
                raise BusyAutomationError(
                    f"Could not set the Account Ledger {label} field to {value!r}."
                )
            return
        if not focus_keys:
            raise BusyAutomationError(
                f"Account Ledger {label} is not calibrated. Set its control or "
                "focus keys in config/busy_ui_profile.json."
            )
        session.send_keys(focus_keys)
        session.send_keys("^a")
        session.type_text(value)
        if self.profile.date_commit_keys:
            session.send_keys(self.profile.date_commit_keys)

    def _set_date(
        self,
        session: BusySessionProtocol,
        *,
        control: Mapping[str, object] | None,
        focus_keys: str | None,
        value: date,
        field_name: str,
    ) -> None:
        text = value.strftime(self.profile.date_format)
        if control:
            if not session.set_text_anywhere(control, text):
                raise BusyAutomationError(
                    f"Could not set the Account Ledger {field_name} to {text}."
                )
        elif focus_keys:
            session.send_keys(focus_keys)
            session.send_keys("^a")
            session.send_keys(text)
        else:
            raise BusyAutomationError(
                f"Account Ledger {field_name} is not calibrated. Set its "
                "control or focus keys in config/busy_ui_profile.json."
            )
        if self.profile.date_commit_keys:
            session.send_keys(self.profile.date_commit_keys)

    def _set_option(
        self,
        session: BusySessionProtocol,
        *,
        label: str,
        control: Mapping[str, object] | None,
        focus_keys: str | None,
        value: bool,
    ) -> None:
        if control:
            if not session.set_checkbox(control, value):
                raise BusyAutomationError(
                    f"Could not set the Account Ledger option {label!r}."
                )
            return
        if focus_keys:
            session.send_keys(focus_keys)
            session.send_keys("y" if value else "n")
            return
        raise BusyAutomationError(
            f"Account Ledger option {label!r} is not calibrated. Set its "
            "control or focus keys in config/busy_ui_profile.json."
        )


class AccountLedgerSalesRecipe(AccountLedgerRecipe):
    category = "bills"


class AccountLedgerSalesReturnRecipe(AccountLedgerRecipe):
    category = "credit_notes"


class PurchaseReturnRecipe(AccountLedgerRecipe):
    category = "debit_notes"


def recipe_for_category(
    profile: BusyUiProfile, category: str
) -> BusyReportRecipe:
    """Return the calibrated recipe for one document category."""

    if category == "bills":
        return AccountLedgerSalesRecipe(profile.account_ledger_sales)
    if category == "credit_notes":
        return AccountLedgerSalesReturnRecipe(profile.account_ledger_sales_return)
    if category == "debit_notes":
        return PurchaseReturnRecipe(profile.purchase_return)
    raise BusyAutomationError(f"Unknown BUSY document category: {category}")
