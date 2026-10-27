"""Small platform adapter for the local Windows folder picker."""

from __future__ import annotations

import platform
from pathlib import Path


class FolderPickerUnavailableError(RuntimeError):
    """Raised when a native picker cannot be opened in this environment."""


def pick_folder() -> Path:
    """Open a native folder dialog and return the selected directory.

    The dashboard is designed for a local Windows workstation. Returning a clear error on
    other platforms keeps the API testable and lets the frontend fall back to manual paths.
    """

    if platform.system() != "Windows":
        raise FolderPickerUnavailableError("The native folder picker is available on Windows only")
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as exc:
        raise FolderPickerUnavailableError("Python Tk support is not installed") from exc

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.askdirectory(title="Choose a document folder", mustexist=True)
    finally:
        root.destroy()
    if not selected:
        raise FolderPickerUnavailableError("Folder selection was cancelled")
    path = Path(selected).expanduser().resolve()
    if not path.is_dir():
        raise FolderPickerUnavailableError("The selected path is not a directory")
    return path
