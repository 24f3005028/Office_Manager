"""Inspect the live BUSY 21 window tree without sending any keys.

Use this while BUSY is open and logged into the expected company:

    .\\.venv\\Scripts\\python.exe scripts/inspect_busy_ui.py
    .\\.venv\\Scripts\\python.exe scripts/inspect_busy_ui.py --watch
    .\\.venv\\Scripts\\python.exe scripts/inspect_busy_ui.py --controls

The default mode prints the main window and every visible top-level window.
``--watch`` keeps printing as you navigate BUSY manually, and ``--controls``
dumps the controls of the main window and any visible dialogs. No menu keys,
no exports and no dialogs are touched by this tool.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import Settings  # noqa: E402
from app.domains.busy_automation.errors import (  # noqa: E402
    BusyAutomationError,
    BusyWrongCompanyError,
)
from app.domains.busy_automation.profile import load_profile  # noqa: E402
from app.domains.busy_automation.session import (  # noqa: E402
    BusySession,
    title_matches,
    verify_company_title,
)


def _rectangle(window: Any) -> str:
    try:
        rect = window.rectangle()
        return f"({rect.left},{rect.top})-({rect.right},{rect.bottom})"
    except Exception:
        return "?"


def _window_info(window: Any, *, include_controls: bool = False) -> dict[str, Any]:
    try:
        title = window.window_text()
    except Exception:
        title = ""
    try:
        class_name = window.class_name()
    except Exception:
        class_name = ""
    try:
        handle = int(window.handle)
    except Exception:
        handle = 0
    try:
        process_id = int(window.process_id())
    except Exception:
        process_id = 0
    try:
        visible = bool(window.is_visible())
    except Exception:
        visible = False
    try:
        enabled = bool(window.is_enabled())
    except Exception:
        enabled = False
    info: dict[str, Any] = {
        "title": title,
        "class_name": class_name,
        "handle": handle,
        "process_id": process_id,
        "rectangle": _rectangle(window),
        "visible": visible,
        "enabled": enabled,
    }
    if include_controls:
        info["controls"] = _control_infos(window)
    return info


def _control_infos(window: Any, limit: int = 400) -> list[dict[str, Any]]:
    controls: list[dict[str, Any]] = []
    try:
        descendants = window.descendants()
    except Exception:
        return controls
    for control in descendants:
        if len(controls) >= limit:
            controls.append(
                {"note": f"Stopped after {limit} controls; use --max-controls."}
            )
            break
        try:
            if not control.is_visible():
                continue
        except Exception:
            pass
        try:
            title = control.window_text()
        except Exception:
            title = ""
        try:
            class_name = control.class_name()
        except Exception:
            class_name = ""
        try:
            control_id = int(control.control_id())
        except Exception:
            control_id = 0
        try:
            auto_id = str(control.automation_id())
        except Exception:
            auto_id = ""
        try:
            control_type = str(control.friendly_class_name())
        except Exception:
            control_type = ""
        controls.append(
            {
                "title": title,
                "class_name": class_name,
                "control_id": control_id,
                "auto_id": auto_id,
                "control_type": control_type,
                "rectangle": _rectangle(control),
            }
        )
    return controls


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def _print_windows(session: BusySession, *, json_output: bool) -> None:
    main = session.main_window
    dialogs = session.visible_dialogs()
    payload: dict[str, Any] = {
        "main": _window_info(main),
        "dialogs": [_window_info(dialog) for dialog in dialogs],
    }
    if json_output:
        _print_json(payload)
        return
    print("BUSY main window")
    print(f"  title      : {payload['main']['title']}")
    print(f"  class      : {payload['main']['class_name']}")
    print(f"  handle     : {payload['main']['handle']}")
    print(f"  rectangle  : {payload['main']['rectangle']}")
    print(f"  visible    : {payload['main']['visible']}")
    if not dialogs:
        print("No other visible top-level windows.")
        return
    print(f"\nVisible top-level windows ({len(dialogs)})")
    for index, info in enumerate(payload["dialogs"], start=1):
        print(
            f"  {index}. {info['title']!r} "
            f"[{info['class_name']}] handle={info['handle']} "
            f"{info['rectangle']}"
        )


def _print_controls(
    session: BusySession,
    *,
    title_re: str | None,
    include_main: bool,
    max_controls: int,
    json_output: bool,
) -> None:
    windows: list[tuple[str, Any]] = []
    if include_main:
        windows.append(("main", session.main_window))
    for index, dialog in enumerate(session.visible_dialogs(), start=1):
        title = session.window_title(dialog)
        if title_re and not title_matches(title_re, title):
            continue
        windows.append((f"dialog {index}", dialog))

    payload: dict[str, Any] = {}
    for label, window in windows:
        info = _window_info(window, include_controls=True)
        controls = info.get("controls", [])
        if len(controls) > max_controls:
            info["controls"] = controls[:max_controls]
            info["controls_truncated"] = True
        payload[label] = info
    if json_output:
        _print_json(payload)
        return
    for label, info in payload.items():
        print(f"\n{label}: {info['title']!r} [{info['class_name']}]")
        for control in info["controls"]:
            if "note" in control:
                print(f"  {control['note']}")
                continue
            print(
                f"  title={control['title']!r} class={control['class_name']!r} "
                f"id={control['control_id']} type={control['control_type']!r} "
                f"rect={control['rectangle']}"
            )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect the live BUSY 21 window tree without sending keys."
    )
    parser.add_argument(
        "--executable",
        type=Path,
        default=None,
        help="BUSY executable path (default: BUSY_EXECUTABLE_PATH).",
    )
    parser.add_argument(
        "--title-re",
        default=None,
        help="Main window title regex (default: BUSY_WINDOW_TITLE_RE).",
    )
    parser.add_argument(
        "--company",
        default=None,
        help="Expected company substring (default: BUSY_EXPECTED_COMPANY_SUBSTRING).",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=None,
        help="UI profile path (default: BUSY_UI_PROFILE_PATH).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Attach timeout in seconds (default: BUSY_AUTOMATION_TIMEOUT_SECONDS).",
    )
    parser.add_argument(
        "--require-company",
        action="store_true",
        help="Fail if the main window title does not contain the expected company.",
    )
    parser.add_argument(
        "--controls",
        action="store_true",
        help="Dump visible controls of the main window and dialogs.",
    )
    parser.add_argument(
        "--dialog-title-re",
        default=None,
        help="Only dump controls for dialogs whose title contains this text.",
    )
    parser.add_argument(
        "--no-main-controls",
        action="store_true",
        help="Skip the main window when dumping controls.",
    )
    parser.add_argument(
        "--max-controls",
        type=int,
        default=400,
        help="Maximum controls to dump per window (default: 400).",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Keep printing the window tree while you navigate BUSY manually.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Watch refresh interval in seconds (default: 2).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of human-readable text.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = Settings()
    profile_path = args.profile or settings.busy_ui_profile_path
    profile = load_profile(profile_path)
    executable = args.executable or settings.busy_executable_path
    title_re = args.title_re or settings.busy_window_title_re
    company = args.company or settings.busy_expected_company_substring
    timeout = args.timeout or settings.busy_automation_timeout_seconds

    try:
        session = BusySession.attach(
            executable_path=executable,
            title_re=title_re,
            expected_company=company,
            profile=profile,
            timeout=timeout,
            require_company=False,
        )
    except BusyAutomationError as exc:
        print(f"Could not attach to BUSY: {exc}", file=sys.stderr)
        return 2

    try:
        if args.require_company:
            try:
                verify_company_title(session.window_title(session.main_window), company)
            except BusyWrongCompanyError as exc:
                print(f"Company guard failed: {exc}", file=sys.stderr)
                return 3
        elif company:
            try:
                verify_company_title(session.window_title(session.main_window), company)
            except BusyWrongCompanyError as exc:
                print(f"WARNING: {exc}", file=sys.stderr)

        print(f"Profile: {profile_path}")
        print(f"Executable: {executable}")
        print(f"Expected company: {company!r}")
        if args.watch:
            try:
                while True:
                    if not args.json:
                        print("\n" + "=" * 72)
                    _print_windows(session, json_output=args.json)
                    if args.controls:
                        _print_controls(
                            session,
                            title_re=args.dialog_title_re,
                            include_main=not args.no_main_controls,
                            max_controls=args.max_controls,
                            json_output=args.json,
                        )
                    time.sleep(max(args.interval, 0.2))
            except KeyboardInterrupt:
                print("\nStopped watching.")
                return 0
        _print_windows(session, json_output=args.json)
        if args.controls:
            _print_controls(
                session,
                title_re=args.dialog_title_re,
                include_main=not args.no_main_controls,
                max_controls=args.max_controls,
                json_output=args.json,
            )
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
