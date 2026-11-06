"""Print-style all-account PDF, generated from the same verified data as the app."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors  # type: ignore[import-untyped]
from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
from reportlab.lib.styles import ParagraphStyle  # type: ignore[import-untyped]
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, TableStyle  # type: ignore[import-untyped]


def indian_amount(value: str | Decimal | None) -> str:
    if value is None:
        return ""
    number = Decimal(value)
    sign = "-" if number < 0 else ""
    whole, fraction = f"{abs(number):.2f}".split(".")
    tail = whole[-3:]
    lead = whole[:-3]
    groups: list[str] = []
    while lead:
        groups.insert(0, lead[-2:])
        lead = lead[:-2]
    return sign + ",".join([*groups, tail]) + "." + fraction


def render_all_pdf(snapshot: dict[str, Any], path: Path, template: Path | None = None) -> None:
    header = snapshot.get("company_header", ["H.S. TRADERS"])
    if template is not None and template.is_file():
        configured = json.loads(template.read_text(encoding="utf-8"))
        lines = configured.get("company_header")
        if (
            isinstance(lines, list)
            and 1 <= len(lines) <= 6
            and all(isinstance(line, str) and len(line) <= 300 for line in lines)
        ):
            header = lines
    paragraph = ParagraphStyle("outstanding-cell", fontName="Helvetica", fontSize=6.5, leading=8)
    heading = ParagraphStyle(
        "outstanding-heading", parent=paragraph, fontName="Helvetica-Bold", fontSize=6.2, leading=8
    )
    compact_heading = ParagraphStyle("compact-heading", parent=heading, fontSize=5.2, leading=7)

    def text(value: Any, bold: bool = False) -> Any:
        style = (
            compact_heading
            if bold and value in {"DISCOUNT", "Due Days"}
            else heading
            if bold
            else paragraph
        )
        return Paragraph(escape(str(value or "")), style)

    widths = [22, 145, 58, 47, 92, 62, 62, 35, 32]
    # A4 printable width, with the same nine columns as the supplied BUSY printout.
    width = A4[0] - 40
    widths = [value * width / sum(widths) for value in widths]
    rows: list[list[Any]] = [
        [
            text(label, True)
            for label in [
                "S.No.",
                "Account",
                "BROKER",
                "Dated",
                "Ref. No.",
                "Ref. Amt.",
                "Pending Amt.",
                "DISCOUNT",
                "Due Days",
            ]
        ]
    ]
    commands: list[tuple[Any, ...]] = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 6.5),
        ("LEADING", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 1), (0, -1), "RIGHT"),
        ("ALIGN", (5, 1), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("BOX", (0, 0), (-1, -1), 0.35, colors.grey),
        ("LINEBELOW", (0, 0), (-1, 0), 0.35, colors.grey),
    ]
    reference_total = Decimal("0.00")
    all_references_known = True
    for number, account in enumerate(snapshot["accounts"], 1):
        group_start = len(rows)
        reference = Decimal("0.00")
        bills = account["bills"]
        references_known = bool(bills) and all(
            bill["reference_amount"] is not None for bill in bills
        )
        all_references_known = all_references_known and references_known
        if not bills:
            rows.append(
                [
                    str(number),
                    text(account["party_name"]),
                    text(account.get("broker", "")),
                    "",
                    "",
                    "",
                    indian_amount(account["pending_amount"]),
                    "",
                    "",
                ]
            )
        for index, bill in enumerate(bills):
            ref = (
                Decimal(bill["reference_amount"])
                if bill["reference_amount"] is not None
                else Decimal("0.00")
            )
            reference += ref
            rows.append(
                [
                    str(number) if index == 0 else "",
                    text(account["party_name"] if index == 0 else ""),
                    text(bill.get("broker") if index == 0 else ""),
                    date.fromisoformat(bill["date"]).strftime("%d-%m-%Y"),
                    text(bill["bill_number"]),
                    indian_amount(bill["reference_amount"]),
                    indian_amount(bill["pending_amount"]),
                    str(bill.get("discount") or "")
                    if str(bill.get("discount") or "0") not in {"0", "0.0", "0.00"}
                    else "",
                    str(bill["due_days"]) if bill["due_days"] is not None else "",
                ]
            )
        if bills:
            rows.append(
                [
                    "",
                    "",
                    "",
                    "",
                    "Total",
                    indian_amount(reference if references_known else None),
                    indian_amount(account["pending_amount"]),
                    "",
                    "",
                ]
            )
        reference_total += reference
        group_end = len(rows) - 1
        commands.append(("LINEBELOW", (0, group_end), (-1, group_end), 0.35, colors.grey))
        # Keep ordinary account groups together; long accounts can continue on another page.
        if group_end - group_start < 35:
            commands.append(("NOSPLIT", (0, group_start), (-1, group_end)))
    rows.append(
        [
            "",
            "",
            "",
            "",
            "Grand Total",
            indian_amount(reference_total)
            if snapshot["layout"] == "bills" and all_references_known
            else "",
            indian_amount(snapshot["pending_amount"]),
            "",
            "",
        ]
    )
    commands.extend(
        [
            ("FONTNAME", (4, -1), (6, -1), "Helvetica-Bold"),
            ("LINEABOVE", (0, -1), (-1, -1), 0.6, colors.black),
        ]
    )
    for column in range(1, 9):
        commands.append(("LINEBEFORE", (column, 0), (column, -1), 0.3, colors.grey))
    table = LongTable(
        rows,
        colWidths=widths,
        repeatRows=1,
        hAlign="LEFT",
        splitByRow=1,
        style=TableStyle(commands),
    )
    top = 104 + max(0, len(header) - 3) * 10
    document = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=20,
        rightMargin=20,
        topMargin=top,
        bottomMargin=32,
        title="H.S. TRADERS - All accounts outstanding",
        author="H.S. TRADERS",
    )

    def page_header(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        y = A4[1] - 27
        for index, line in enumerate(header):
            canvas.setFont("Helvetica-Bold" if index == 0 else "Helvetica", 13 if index == 0 else 8)
            canvas.drawCentredString(A4[0] / 2, y, line)
            y -= 16 if index == 0 else 10
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawCentredString(A4[0] / 2, y - 2, "Bills Receivable")
        canvas.setFont("Helvetica", 8)
        canvas.drawString(20, y - 17, "All Accounts")
        canvas.drawRightString(A4[0] - 20, y - 17, "On Basis of : Due Date")
        start = date.fromisoformat(snapshot["start_date"]).strftime("%d-%m-%Y")
        end = date.fromisoformat(snapshot["as_of"]).strftime("%d-%m-%Y")
        canvas.drawString(20, y - 28, f"From {start} to {end}")
        canvas.drawRightString(A4[0] - 20, y - 28, f"Bills Status as on : {end}")
        canvas.setFont("Helvetica", 7)
        canvas.drawRightString(A4[0] - 20, 18, f"Page {doc.page}")
        canvas.restoreState()

    document.build([table], onFirstPage=page_header, onLaterPages=page_header)
