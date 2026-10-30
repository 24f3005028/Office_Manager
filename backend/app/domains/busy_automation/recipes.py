"""BUSY report recipes.

Phase 2 implements the Sales Register only. Credit Note and Debit Note recipes
are added after the live UI profile has been calibrated with
``scripts/inspect_busy_ui.py``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from app.domains.busy_automation.errors import BusyAutomationError
from app.domains.busy_automation.profile import BusyRecipeProfile
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
