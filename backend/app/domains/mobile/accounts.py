"""Read account names and their direct BUSY group, without contact or balance data."""

from __future__ import annotations

from io import BytesIO

from openpyxl import load_workbook  # type: ignore[import-untyped]


def account_rows(content: bytes) -> list[dict[str, str]]:
    workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    try:
        sheet = workbook.active
        if sheet is None or sheet.max_row > 50000 or sheet.max_column > 100:
            raise ValueError("The account workbook is too large or empty.")
        accounts: dict[str, dict[str, str]] = {}
        columns: tuple[int, int] | None = None
        for row in sheet.iter_rows(values_only=True):
            values = [str(value).strip() if value is not None else "" for value in row]
            lowered = [value.casefold() for value in values]
            if columns is None:
                if "name" in lowered and "parent group" in lowered:
                    columns = lowered.index("name"), lowered.index("parent group")
                continue
            if len(values) <= max(columns):
                continue
            name, group = values[columns[0]], values[columns[1]]
            if name and group:
                if (
                    len(name) > 200
                    or len(group) > 100
                    or any(ord(char) < 32 for char in name + group)
                ):
                    raise ValueError("An account name contains unsupported characters.")
                old = accounts.get(name.casefold())
                if old and old["group"].casefold() != group.casefold():
                    raise ValueError("An account has conflicting groups in the export.")
                accounts[name.casefold()] = {"name": name, "group": group}
        if columns is None or not accounts:
            raise ValueError(
                "Use BUSY's List of Accounts export with Name and Parent Group columns."
            )
        return sorted(accounts.values(), key=lambda row: row["name"].casefold())
    finally:
        workbook.close()


def account_names(content: bytes) -> list[str]:
    return sorted(
        {
            row["name"]
            for row in account_rows(content)
            if row["group"].casefold() in {"sundry debtors", "sundry creditors"}
        },
        key=str.casefold,
    )
