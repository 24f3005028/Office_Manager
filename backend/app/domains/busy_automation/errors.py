"""Errors raised by the BUSY desktop automation pipeline."""

from __future__ import annotations


class BusyAutomationError(RuntimeError):
    """Base error for a failed BUSY automation operation."""


class BusyNotRunningError(BusyAutomationError):
    """BUSY is not running, cannot be attached to, or pywinauto is unavailable."""


class BusyWrongCompanyError(BusyAutomationError):
    """The attached BUSY window does not belong to the expected company."""


class BusyUnsafeStateError(BusyAutomationError):
    """BUSY is in a state where automation could discard unsaved user work."""


class BusyUserActiveError(BusyAutomationError):
    """The user is actively using the desktop and automation should wait."""


class BusyLockTimeoutError(BusyAutomationError):
    """Another automation task still holds the BUSY desktop lock."""


class BusyExportError(BusyAutomationError):
    """BUSY did not produce a usable Excel export."""
