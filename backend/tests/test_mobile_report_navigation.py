"""Check the supported BUSY route and fail-closed PDF export behaviour."""

from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pymupdf
import pytest
from app.config import Settings
from app.domains.mobile import reports
from app.domains.mobile.reports import OutstandingExporter
from app.domains.pouncha_sync.parser import SyncError


@pytest.mark.parametrize("wrong_party", [False, True])
def test_native_export_pdf_layout_keeps_party_and_totals_checks(
    tmp_path: Path, wrong_party: bool
) -> None:
    path = tmp_path / "export.pdf"
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text(
            (30, 30),
            "H.S. TRADERS\nBills Receivable\nAccount : RAJAN TEXTILES\n"
            "On Basis of : Due Date\nFrom 16-1-2025 to 5-11-2026\n"
            "Bills Status as on : 5-11-2026\n"
            "Dated Type Ref. No. Ref. Amt. Pending Amt. Due Due Date Due Day\n"
            "Total 6,83,544.00 6,83,544.00\n"
            "( On Acc. : 0.00 ; Ledger Bal. : 6,83,544.00 Dr )",
        )
        document.save(path)
    if wrong_party:
        with pytest.raises(SyncError, match="party or report dates"):
            reports.verify_report(path, "OTHER PARTY", date(2026, 11, 5))
    else:
        assert (
            reports.verify_report(path, "RAJAN TEXTILES", date(2026, 11, 5))["pending_amount"]
            == "683544.00"
        )


def test_favourites_initial_selects_outstanding_before_one_account() -> None:
    exporter = OutstandingExporter(Settings(_env_file=None))
    root = Mock()
    exporter._home = Mock(return_value=True)
    exporter._guard = Mock(return_value=[root])
    exporter._buttons = Mock(return_value=[Mock()])
    exporter._edits = Mock(return_value=[Mock()] * 19)
    exporter._click = Mock()
    assert exporter._open_outstanding(root, None) is root
    assert [call.args[0] for call in root.type_keys.call_args_list] == ["%f", "o", "{ENTER}"]
    exporter._click.assert_called_once_with(root, "One Account")


def test_no_favourite_shortcut_when_home_recovery_fails() -> None:
    exporter = OutstandingExporter(Settings(_env_file=None))
    root = Mock()
    exporter._home = Mock(return_value=False)
    with pytest.raises(SyncError, match="15 Escape"):
        exporter._open_outstanding(root, None)
    root.type_keys.assert_not_called()


@pytest.mark.parametrize("auxiliary", [False, True])
def test_direct_pdf_export_commits_format_and_dismisses_open_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, auxiliary: bool
) -> None:
    exporter = OutstandingExporter(Settings(_env_file=None))
    report, dialog, prompt = Mock(), Mock(), Mock()
    dialog.window_text.return_value = "Export Data"
    prompt.window_text.return_value = "Open File Now ?"
    format_field, filename_field = Mock(), Mock()
    format_field.get_value.return_value = "PDF"
    fields = [format_field, filename_field]
    if auxiliary:
        blank = Mock()
        blank.get_value.return_value = ""
        fields.append(blank)
    exporter._edits = Mock(return_value=fields)
    exporter._guard = Mock(side_effect=[[dialog], [dialog], [prompt]] + [[dialog]] * 5)
    exporter._set = Mock()
    path = tmp_path / "PARTY.pdf"

    def click(root: Mock, name: str) -> None:
        if name == "OK":
            path.write_bytes(b"verified by the separate PDF verifier")

    exporter._click = Mock(side_effect=click)
    verify = Mock()
    monkeypatch.setattr(reports, "verify_report", verify)
    monkeypatch.setattr(reports.time, "sleep", lambda _: None)
    day = date(2026, 11, 5)
    assert exporter._export_pdf(None, None, report, tmp_path, "PARTY", day) == path
    report.type_keys.assert_called_once_with("%e", pause=0.2)
    format_field.type_keys.assert_called_once_with("p{ENTER}", pause=0.2)
    assert exporter._set.call_args_list[-1].args == (filename_field, str(path))
    assert any(call.args == (prompt, "No") for call in exporter._click.call_args_list)
    verify.assert_called_once_with(path, "PARTY", day)
