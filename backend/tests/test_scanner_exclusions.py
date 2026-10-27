from pathlib import Path

from app.domains.documents.scanner import DocumentScanner


def write_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4 fixture")


def test_scanner_skips_busy_and_system_directories_case_insensitively(tmp_path: Path) -> None:
    root = tmp_path / "documents"
    for folder in (
        "BusyWin",
        "busywin/Nested",
        "EInvoiceTemp",
        "EWayBillTemp",
        "SYSTEM",
        "XMPPMessages",
    ):
        write_pdf(root / folder / "HST-1 hidden.pdf")
    write_pdf(root / "HSL-1 visible.pdf")
    write_pdf(root / "2026" / "HSL-2 visible.pdf")

    records = DocumentScanner({"bills": (root,)}).scan(("bills",))

    assert [record.file_name for record in records] == [
        "HSL-1 visible.pdf",
        "HSL-2 visible.pdf",
    ]


def test_scanner_ignore_list_is_configurable(tmp_path: Path) -> None:
    root = tmp_path / "documents"
    write_pdf(root / "BusyWin" / "HST-1 busy.pdf")
    write_pdf(root / "Custom" / "HST-2 custom.pdf")
    write_pdf(root / "HSL-3 visible.pdf")

    scanner = DocumentScanner(
        {"bills": (root,)}, ignored_directory_names=("Custom",)
    )

    records = scanner.scan(("bills",))

    assert [record.file_name for record in records] == [
        "HSL-3 visible.pdf",
        "HST-1 busy.pdf",
    ]
