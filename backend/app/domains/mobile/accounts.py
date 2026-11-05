"""Import only trade account names from a BUSY List of Accounts export."""

from __future__ import annotations

from io import BytesIO

from openpyxl import load_workbook  # type: ignore[import-untyped]


def account_names(content: bytes) -> list[str]:
    workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    try:
        sheet = workbook.active
        if sheet is None or sheet.max_row > 50000 or sheet.max_column > 100:
            raise ValueError("The account workbook is too large or empty.")
        names: set[str] = set()
        columns: tuple[int, int] | None = None
        for row in sheet.iter_rows(values_only=True):
            values = [str(value).strip() if value is not None else "" for value in row]
            lowered = [value.casefold() for value in values]
            if columns is None:
                if "name" in lowered and "parent group" in lowered:
                    columns = lowered.index("name"), lowered.index("parent group")
                continue
            name, group = values[columns[0]], values[columns[1]]
            if group.casefold() in {"sundry debtors", "sundry creditors"} and name:
                if len(name) > 200 or any(ord(char) < 32 for char in name):
                    raise ValueError("An account name contains unsupported characters.")
                names.add(name)
        if columns is None or not names:
            raise ValueError(
                "Use BUSY's List of Accounts export with Name and Parent Group columns."
            )
        return sorted(names, key=str.casefold)
    finally:
        workbook.close()
