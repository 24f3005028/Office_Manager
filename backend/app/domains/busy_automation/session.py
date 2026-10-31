"""Safe attachment to the BUSY 21 desktop window.

pywinauto is imported lazily so the rest of the backend, and the test suite,
works on machines that do not have Windows UI automation dependencies.

The session never closes BUSY, never kills Excel, and never answers an unknown
dialog by guessing. A wrong company title or an unexpected modal window stops
the automation with a clear error instead of risking user data.
"""

from __future__ import annotations

import logging
import re
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.domains.busy_automation.errors import (
    BusyAutomationError,
    BusyNotRunningError,
    BusyUnsafeStateError,
    BusyWrongCompanyError,
)
from app.domains.busy_automation.profile import BusyUiProfile

logger = logging.getLogger(__name__)

_SPEC_KEYS = frozenset(
    {
        "title",
        "title_re",
        "class_name",
        "control_id",
        "auto_id",
        "control_type",
        "found_index",
    }
)
_IGNORED_WINDOW_CLASSES = frozenset(
    {"MdiClient", "tooltips_class32", "SysHeader32", "#32768", "ComboLBox"}
)


def _normalize_company(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def verify_company_title(title: str, expected: str) -> None:
    """Fail unless ``title`` belongs to the expected company.

    Punctuation and spacing are ignored so ``H.S. Traders``, ``H S Traders`` and
    ``H.S.Traders`` all match. The comparison itself is case-insensitive.
    """

    expected_text = expected.strip()
    if not expected_text:
        return
    if _normalize_company(expected_text) not in _normalize_company(title):
        raise BusyWrongCompanyError(
            f"BUSY is showing {title!r}, which does not match the expected company "
            f"{expected_text!r}. Open the correct company before running automation."
        )


def title_matches(pattern: str, title: str) -> bool:
    """Return whether a window title matches a profile regex."""

    if not pattern:
        return False
    return re.search(pattern, title, re.IGNORECASE) is not None


@dataclass(frozen=True, slots=True)
class BusyWindowInfo:
    """A visible top-level window discovered through the Win32 API."""

    handle: int
    pid: int
    title: str
    class_name: str
    executable_path: str | None
    width: int
    height: int

    @property
    def area(self) -> int:
        return self.width * self.height


def _visible_top_level_windows() -> list[BusyWindowInfo]:
    """Enumerate visible top-level windows without WMI or pywinauto scans."""

    if sys.platform != "win32":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.EnumWindows.argtypes = [
            ctypes.WINFUNCTYPE(
                wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
            ),
            wintypes.LPARAM,
        ]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetClassNameW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        user32.GetClassNameW.restype = ctypes.c_int
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetWindowRect.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.RECT),
        ]
        user32.GetWindowRect.restype = wintypes.BOOL
        kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        process_paths: dict[int, str | None] = {}

        def process_path(pid: int) -> str | None:
            if pid in process_paths:
                return process_paths[pid]
            path: str | None = None
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                try:
                    size = wintypes.DWORD(32768)
                    buffer = ctypes.create_unicode_buffer(size.value)
                    if kernel32.QueryFullProcessImageNameW(
                        handle, 0, buffer, ctypes.byref(size)
                    ):
                        path = buffer.value
                finally:
                    kernel32.CloseHandle(handle)
            process_paths[pid] = path
            return path

        windows: list[BusyWindowInfo] = []

        @ctypes.WINFUNCTYPE(  # type: ignore[untyped-decorator]
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )
        def _callback(hwnd: int, _lparam: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            title_buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title_buffer, length + 1)
            rectangle = wintypes.RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rectangle)):
                return True
            width = rectangle.right - rectangle.left
            height = rectangle.bottom - rectangle.top
            if width <= 0 or height <= 0:
                return True
            class_buffer = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buffer, 256)
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            windows.append(
                BusyWindowInfo(
                    handle=int(hwnd),
                    pid=int(pid.value),
                    title=title_buffer.value,
                    class_name=class_buffer.value,
                    executable_path=process_path(int(pid.value)),
                    width=width,
                    height=height,
                )
            )
            return True

        user32.EnumWindows(_callback, 0)
        return windows
    except Exception as exc:  # pragma: no cover - Windows API failure
        logger.debug("Could not enumerate the BUSY windows: %s", exc)
        return []


def find_busy_window(
    *,
    title_re: str,
    executable_path: Path | None = None,
    pid: int | None = None,
    handle: int | None = None,
) -> BusyWindowInfo | None:
    """Find the visible BUSY window by handle, PID, title, or executable path.

    The executable path is compared with ``QueryFullProcessImageNameW`` from a
    direct process handle, so discovery does not perform a WMI query or a slow
    pywinauto path scan. When both a title and a path are supplied, a window
    matching both wins; a title-only or path-only match is still accepted so a
    changed window title or a moved executable does not break attachment.
    """

    windows = _visible_top_level_windows()
    if handle is not None:
        return next(
            (window for window in windows if window.handle == int(handle)), None
        )

    target_path = (
        str(executable_path).casefold() if executable_path is not None else None
    )
    if not title_re and target_path is None and pid is None:
        return None

    ranked: list[tuple[tuple[int, int, int], BusyWindowInfo]] = []
    for window in windows:
        if pid is not None and window.pid != pid:
            continue
        title_ok = bool(title_re) and title_matches(title_re, window.title)
        path_ok = bool(target_path) and (
            window.executable_path is not None
            and window.executable_path.casefold() == target_path
        )
        if pid is None and not title_ok and not path_ok:
            continue
        rank = (
            1 if title_ok and path_ok else 0,
            1 if title_ok else 0,
            window.area,
        )
        ranked.append((rank, window))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


def _busy_window_summary() -> str:
    windows = _visible_top_level_windows()
    interesting = [
        window
        for window in windows
        if "busy" in window.class_name.casefold()
        or "busy" in window.title.casefold()
    ]
    if not interesting:
        return "No visible BUSY window was found."
    return "; ".join(
        f"{window.title!r} pid={window.pid} class={window.class_name}"
        for window in interesting[:8]
    )


def busy_window_visible(
    title_re: str, executable_path: Path | None = None
) -> bool:
    """Return whether a visible top-level window matches BUSY.

    This is a read-only probe used by the scheduler to skip catch-up runs
    quietly while BUSY is closed. It never attaches to or starts BUSY.
    """

    return (
        find_busy_window(
            title_re=title_re, executable_path=executable_path
        )
        is not None
    )


class BusySessionProtocol(Protocol):
    """The subset of the session used by recipes and the exporter."""

    timeout: float

    def ensure_main_menu(self) -> None: ...

    def focus(self, window: Any | None = None) -> None: ...

    def send_keys(self, keys: str, *, window: Any | None = None) -> None: ...

    def type_text(self, text: str, *, window: Any | None = None) -> None: ...

    def wait_for_dialog(self, title_re: str, timeout: float) -> Any: ...

    def find_dialog(self, title_re: str) -> Any | None: ...

    def visible_dialogs(self) -> list[Any]: ...

    def wait_for_title(self, title_re: str, timeout: float) -> str: ...

    def set_text(self, window: Any, spec: Mapping[str, Any], text: str) -> bool: ...

    def set_text_anywhere(self, spec: Mapping[str, Any], text: str) -> bool: ...

    def set_control_text(self, control: Any, text: str) -> bool: ...

    def click(self, window: Any, spec: Mapping[str, Any]) -> bool: ...

    def set_checkbox(self, spec: Mapping[str, Any], checked: bool) -> bool: ...

    def select_combo_item(self, spec: Mapping[str, Any], value: str) -> bool: ...

    def uncheck(self, control: Any) -> bool: ...

    def find_children(
        self, window: Any, spec: Mapping[str, Any]
    ) -> list[Any]: ...

    def window_title(self, window: Any) -> str: ...

    def window_handle(self, window: Any) -> int: ...

    def close(self) -> None: ...


class BusySession:
    """A pywinauto wrapper that only performs guarded desktop actions."""

    def __init__(
        self,
        app: Any,
        main_window: Any,
        *,
        profile: BusyUiProfile,
        timeout: float,
        send_keys_impl: Any,
    ) -> None:
        self._app = app
        self._main = main_window
        self.profile = profile
        self.timeout = timeout
        self._send_keys_impl = send_keys_impl

    @classmethod
    def attach(
        cls,
        *,
        executable_path: Path,
        title_re: str,
        expected_company: str,
        profile: BusyUiProfile,
        timeout: float,
        require_company: bool = True,
        pid: int | None = None,
        handle: int | None = None,
        backend: str | None = None,
    ) -> BusySession:
        """Attach to an already-running BUSY 21 process.

        BUSY is never started automatically: starting a second instance could
        open a different company or create a second data lock. The window is
        discovered with a direct Win32 enumeration and attached by handle, so
        a moved executable or the double space in ``Busy 21  Rel`` does not
        break the connection. ``pid``, ``handle``, and ``backend`` are
        diagnostic overrides for live calibration.
        """

        if sys.platform != "win32":
            raise BusyNotRunningError(
                "BUSY desktop automation is only available on Windows."
            )
        try:
            from pywinauto import Application  # type: ignore[import-untyped]
            from pywinauto.keyboard import send_keys  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - Windows-only dependency
            raise BusyNotRunningError(
                "pywinauto is not installed. Install the Windows backend dependencies."
            ) from exc

        app, main = _connect(
            Application,
            executable_path,
            title_re,
            timeout,
            pid=pid,
            handle=handle,
            backend=backend,
        )
        try:
            main.wait("visible", timeout=timeout)
        except Exception as exc:
            raise BusyNotRunningError(
                f"Could not find the BUSY main window matching {title_re!r}: {exc}"
            ) from exc

        title = _safe_title(main)
        if require_company:
            verify_company_title(title, expected_company)
        try:
            if main.is_minimized():
                main.restore()
        except Exception:
            logger.debug("Could not restore the BUSY main window; continuing.")
        return cls(
            app,
            main,
            profile=profile,
            timeout=timeout,
            send_keys_impl=send_keys,
        )

    @property
    def app(self) -> Any:
        return self._app

    @property
    def main_window(self) -> Any:
        return self._main

    def ensure_main_menu(self) -> None:
        """Return to a neutral BUSY state without discarding user work.

        One or two Escape presses close menus and report windows. Known exit
        prompts are cancelled with ``No``; every other modal window stops the
        automation instead of being dismissed blindly.
        """

        if self._handle_reset_dialogs():
            return
        self.focus()
        for _ in range(2):
            if self._handle_reset_dialogs():
                return
            try:
                self._send_keys_impl("{ESC}", pause=self.profile.key_pause_sec)
            except Exception as exc:
                raise BusyAutomationError(
                    f"Could not return BUSY to its main menu: {exc}"
                ) from exc
            time.sleep(0.3)
            if self._handle_reset_dialogs():
                return
        if self.visible_dialogs():
            titles = [self.window_title(window) for window in self.visible_dialogs()]
            raise BusyUnsafeStateError(
                "BUSY still has an unexpected window open: "
                f"{titles}. Close it manually before running automation."
            )

    def focus(self, window: Any | None = None) -> None:
        target = window if window is not None else self._main
        try:
            is_minimized = getattr(target, "is_minimized", None)
            if callable(is_minimized) and is_minimized():
                target.restore()
        except Exception:
            logger.debug("Could not restore the BUSY window before focusing it.")
        try:
            target.set_focus()
        except Exception as exc:
            raise BusyAutomationError(
                f"Could not focus the BUSY window: {exc}"
            ) from exc

    def send_keys(self, keys: str, *, window: Any | None = None) -> None:
        if window is not None:
            self.focus(window)
        try:
            self._send_keys_impl(keys, pause=self.profile.key_pause_sec)
        except Exception as exc:
            raise BusyAutomationError(
                f"Could not send {keys!r} to BUSY: {exc}"
            ) from exc

    def type_text(self, text: str, *, window: Any | None = None) -> None:
        """Type arbitrary text, preferring a clipboard paste for special characters."""

        if window is not None:
            self.focus(window)
        clipboard: Any = None
        previous: Any = None
        try:
            from pywinauto import clipboard as pywinauto_clipboard

            clipboard = pywinauto_clipboard
            try:
                previous = clipboard.get_data()
            except Exception:
                previous = None
            clipboard.set_data(text)
        except Exception:
            clipboard = None
        if clipboard is not None:
            try:
                self._send_keys_impl("^v", pause=self.profile.key_pause_sec)
            finally:
                if isinstance(previous, str):
                    try:
                        clipboard.set_data(previous)
                    except Exception:
                        logger.debug("Could not restore the clipboard after typing into BUSY.")
            return
        try:
            self._send_keys_impl(
                text, pause=self.profile.key_pause_sec, with_spaces=True
            )
        except Exception as exc:
            raise BusyAutomationError(
                f"Could not type text into BUSY: {exc}"
            ) from exc

    def _handle_reset_dialogs(self) -> bool:
        """Handle dialogs while resetting. Return True if an exit prompt was cancelled."""

        for dialog in self.visible_dialogs():
            title = self.window_title(dialog)
            if title_matches(self.profile.unsafe_dialog_re, title):
                raise BusyUnsafeStateError(
                    "BUSY has a dialog open that may discard or overwrite data: "
                    f"{title!r}. Automation stopped without answering it."
                )
            if title_matches(self.profile.exit_dialog_re, title):
                self.send_keys(self.profile.exit_no_keys, window=dialog)
                logger.info("Cancelled a BUSY exit prompt while resetting to the main menu.")
                return True
            if any(
                title_matches(pattern, title)
                for pattern in self.profile.allowed_dialog_title_res
            ):
                self.send_keys(self.profile.allowed_dialog_dismiss_keys, window=dialog)
                continue
            raise BusyUnsafeStateError(
                f"BUSY has an unexpected window open: {title!r}. "
                "Close it manually before running automation."
            )
        return False

    def visible_dialogs(self) -> list[Any]:
        """Return visible top-level windows other than the BUSY main window."""

        dialogs: list[Any] = []
        seen: set[int] = set()
        main_handle = self.window_handle(self._main)
        process_id = getattr(self._app, "process", None)
        if isinstance(process_id, int):
            for record in _visible_top_level_windows():
                if record.pid != process_id or record.handle == main_handle:
                    continue
                if record.class_name in _IGNORED_WINDOW_CLASSES:
                    continue
                if not record.title.strip() or record.handle in seen:
                    continue
                try:
                    window = self._app.window(handle=record.handle)
                except Exception:
                    continue
                seen.add(record.handle)
                dialogs.append(window)
            return dialogs
        try:
            windows = self._app.windows()
        except Exception:
            return dialogs
        for window in windows:
            handle = self.window_handle(window)
            if handle in seen or handle == main_handle:
                continue
            try:
                if not window.is_visible():
                    continue
                class_name = str(window.class_name())
                title = self.window_title(window)
            except Exception:
                continue
            try:
                rectangle = window.rectangle()
            except Exception:
                rectangle = None
            if rectangle is not None and (
                rectangle.right <= rectangle.left
                or rectangle.bottom <= rectangle.top
            ):
                continue
            if not title.strip() or class_name in _IGNORED_WINDOW_CLASSES:
                continue
            seen.add(handle)
            dialogs.append(window)
        return dialogs

    def find_dialog(self, title_re: str) -> Any | None:
        for dialog in self.visible_dialogs():
            if title_matches(title_re, self.window_title(dialog)):
                return dialog
        return None

    def wait_for_dialog(self, title_re: str, timeout: float) -> Any:
        deadline = time.monotonic() + max(timeout, 0.0)
        while True:
            dialog = self.find_dialog(title_re)
            if dialog is not None:
                title = self.window_title(dialog)
                if title_matches(self.profile.unsafe_dialog_re, title):
                    raise BusyUnsafeStateError(
                        "BUSY showed a dialog that may discard or overwrite data "
                        f"({title!r}); automation stopped without answering it."
                    )
                if title_matches(self.profile.exit_dialog_re, title):
                    raise BusyUnsafeStateError(
                        f"BUSY showed an exit confirmation dialog ({title!r}); "
                        "automation stopped without answering it."
                    )
                return dialog
            self._raise_on_unsafe_dialog()
            if time.monotonic() >= deadline:
                titles = [
                    self.window_title(window) for window in self.visible_dialogs()
                ]
                raise BusyAutomationError(
                    f"BUSY did not show a dialog matching {title_re!r} within "
                    f"{timeout:.1f}s. Visible windows: {titles or 'none'}."
                )
            time.sleep(0.2)

    def wait_for_title(self, title_re: str, timeout: float) -> str:
        deadline = time.monotonic() + max(timeout, 0.0)
        while True:
            titles = [self.window_title(self._main)]
            titles.extend(
                self.window_title(window) for window in self.visible_dialogs()
            )
            for title in titles:
                if title_matches(title_re, title):
                    return title
            try:
                matches = self._main.descendants(title_re=title_re)
            except Exception:
                matches = []
            for match in matches:
                title = self.window_title(match)
                if title_matches(title_re, title):
                    return title
            self._raise_on_unsafe_dialog()
            if time.monotonic() >= deadline:
                titles = [
                    self.window_title(window) for window in self.visible_dialogs()
                ]
                raise BusyAutomationError(
                    f"BUSY did not show a window matching {title_re!r} within "
                    f"{timeout:.1f}s. Visible windows: {titles or 'none'}."
                )
            time.sleep(0.2)

    def set_text(self, window: Any, spec: Mapping[str, Any], text: str) -> bool:
        control = self._first_child(window, spec)
        if control is None:
            return False
        return self.set_control_text(control, text)

    def set_text_anywhere(self, spec: Mapping[str, Any], text: str) -> bool:
        windows = [self._main, *self.visible_dialogs()]
        return any(self.set_text(window, spec, text) for window in windows)

    def set_control_text(self, control: Any, text: str) -> bool:
        try:
            control.set_edit_text(text)
            return True
        except Exception:
            pass
        try:
            control.set_text(text)
            return True
        except Exception:
            pass
        try:
            self.focus(control)
            self._send_keys_impl("^a", pause=self.profile.key_pause_sec)
            self.type_text(text, window=control)
            return True
        except Exception as exc:
            logger.debug("Could not set text on a BUSY control: %s", exc)
            return False

    def click(self, window: Any, spec: Mapping[str, Any]) -> bool:
        control = self._first_child(window, spec)
        if control is None:
            return False
        try:
            control.click_input()
            return True
        except Exception:
            try:
                control.click()
                return True
            except Exception as exc:
                logger.debug("Could not click a BUSY control: %s", exc)
                return False

    def set_checkbox(self, spec: Mapping[str, Any], checked: bool) -> bool:
        """Set a real checkbox/radio control to ``checked`` without guessing."""

        control = self._first_child_anywhere(spec)
        if control is None:
            return False
        state = self._toggle_state(control)
        if state is None:
            logger.debug(
                "Refusing to change a control without a toggle state: %s",
                self.window_title(control),
            )
            return False
        if bool(state) == checked:
            return True
        try:
            control.click_input()
            return True
        except Exception:
            try:
                control.click()
                return True
            except Exception as exc:
                logger.debug("Could not toggle a BUSY checkbox: %s", exc)
                return False

    def select_combo_item(self, spec: Mapping[str, Any], value: str) -> bool:
        """Choose an item in a combo box, verifying the resulting selection."""

        control = self._first_child_anywhere(spec)
        if control is None:
            return False
        try:
            control.select(value)
        except Exception:
            try:
                control.set_edit_text(value)
            except Exception:
                try:
                    self.focus(control)
                    self._send_keys_impl("^a", pause=self.profile.key_pause_sec)
                    self.type_text(value, window=control)
                    self._send_keys_impl("{ENTER}", pause=self.profile.key_pause_sec)
                except Exception as exc:
                    logger.debug("Could not select a BUSY combo item: %s", exc)
                    return False
        try:
            selected = str(control.window_text()).strip()
        except Exception:
            selected = ""
        if selected and selected.casefold() != value.casefold():
            logger.debug(
                "BUSY combo shows %r after selecting %r; continuing.",
                selected,
                value,
            )
        return True

    def uncheck(self, control: Any) -> bool:
        """Uncheck a real checkbox, but never click an unknown control."""

        checked = self._toggle_state(control)
        if checked is None:
            logger.debug(
                "Refusing to uncheck a control without a toggle state: %s",
                self.window_title(control),
            )
            return False
        if not checked:
            return True
        try:
            control.click_input()
            return True
        except Exception:
            try:
                control.click()
                return True
            except Exception as exc:
                logger.debug("Could not uncheck a BUSY checkbox: %s", exc)
                return False

    def find_children(
        self, window: Any, spec: Mapping[str, Any]
    ) -> list[Any]:
        kwargs = self._spec_kwargs(spec)
        if not kwargs:
            return []
        try:
            controls = list(window.descendants(**kwargs))
        except Exception:
            try:
                controls = list(window.children(**kwargs))
            except Exception:
                return []
        visible: list[Any] = []
        for control in controls:
            try:
                if not control.is_visible():
                    continue
            except Exception:
                pass
            visible.append(control)
        return visible

    def window_title(self, window: Any) -> str:
        return _safe_title(window)

    def window_handle(self, window: Any) -> int:
        try:
            return int(window.handle)
        except Exception:
            return id(window)

    def close(self) -> None:
        """Release references only. BUSY and the user's company stay open."""

        self._app = None
        self._main = None

    def _raise_on_unsafe_dialog(self) -> None:
        for dialog in self.visible_dialogs():
            title = self.window_title(dialog)
            if title_matches(self.profile.unsafe_dialog_re, title):
                raise BusyUnsafeStateError(
                    "BUSY showed a dialog that may discard or overwrite data "
                    f"({title!r}); automation stopped without answering it."
                )
            if title_matches(self.profile.exit_dialog_re, title):
                raise BusyUnsafeStateError(
                    f"BUSY showed an exit confirmation dialog ({title!r}); "
                    "automation stopped without answering it."
                )

    def _first_child(self, window: Any, spec: Mapping[str, Any]) -> Any | None:
        children = self.find_children(window, spec)
        return children[0] if children else None

    def _first_child_anywhere(self, spec: Mapping[str, Any]) -> Any | None:
        for window in [self._main, *self.visible_dialogs()]:
            child = self._first_child(window, spec)
            if child is not None:
                return child
        return None

    @staticmethod
    def _toggle_state(control: Any) -> bool | None:
        try:
            if hasattr(control, "get_toggle_state"):
                return bool(control.get_toggle_state())
            if hasattr(control, "is_checked"):
                return bool(control.is_checked())
        except Exception:
            return None
        return None

    @staticmethod
    def _spec_kwargs(spec: Mapping[str, Any]) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        for key, value in spec.items():
            if value is None:
                continue
            if key not in _SPEC_KEYS:
                continue
            kwargs[key] = value
        return kwargs


def _safe_title(window: Any) -> str:
    try:
        return str(window.window_text())
    except Exception:
        return ""


def _connect(
    application_cls: Any,
    executable_path: Path,
    title_re: str,
    timeout: float,
    *,
    pid: int | None = None,
    handle: int | None = None,
    backend: str | None = None,
) -> tuple[Any, Any]:
    window = find_busy_window(
        title_re=title_re,
        executable_path=executable_path,
        pid=pid,
        handle=handle,
    )
    if window is None:
        raise BusyNotRunningError(
            f"Could not find BUSY at {executable_path} matching {title_re!r}. "
            "Start BUSY 21, open the expected company, and try again. "
            f"Visible BUSY windows: {_busy_window_summary()}"
        )

    backends = [backend] if backend else ["win32", "uia"]
    errors: list[str] = []
    for backend_name in backends:
        try:
            app = application_cls(backend=backend_name).connect(
                handle=window.handle, timeout=timeout
            )
            main = app.window(handle=window.handle)
            main.wait("visible", timeout=timeout)
            return app, main
        except Exception as exc:
            errors.append(f"{backend_name} handle {window.handle}: {exc}")
    for backend_name in backends:
        try:
            app = application_cls(backend=backend_name).connect(
                process=window.pid, timeout=timeout
            )
            main = app.window(handle=window.handle)
            main.wait("visible", timeout=timeout)
            return app, main
        except Exception as exc:
            errors.append(f"{backend_name} process {window.pid}: {exc}")

    raise BusyNotRunningError(
        f"Found the BUSY window {window.title!r} (pid {window.pid}), but could "
        f"not attach to it. ({'; '.join(errors)})"
    )

