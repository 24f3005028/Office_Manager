"""Group closing-balance PDF rendered from the same reconciled rows as the app."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors  # type: ignore[import-untyped]
from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
from reportlab.lib.styles import ParagraphStyle  # type: ignore[import-untyped]
from reportlab.platypus import (  # type: ignore[import-untyped]
    LongTable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    TableStyle,
)

from app.domains.mobile.outstanding_pdf import indian_amount


def render_group_pdf(snapshot: dict[str, Any], path: Path) -> None:
    body = ParagraphStyle("balance-cell", fontName="Helvetica", fontSize=9, leading=13)
    heading = ParagraphStyle("balance-heading", parent=body, fontName="Helvetica-Bold", fontSize=10)
    title = ParagraphStyle(
        "balance-title",
        parent=heading,
        fontSize=19,
        leading=26,
        textColor=colors.HexColor("#173b60"),
    )
    sub = ParagraphStyle("balance-subtitle", parent=body, textColor=colors.HexColor("#586b7f"))

    def cell(value: str, bold: bool = False) -> Any:
        return Paragraph(escape(value), heading if bold else body)

    day = date.fromisoformat(snapshot["as_of"])
    header: list[Any] = [
        Paragraph("H.S. TRADERS", title),
        Paragraph("Trial Balance - Group closing balances", heading),
        Paragraph("Group : " + escape(snapshot["group_name"]), sub),
        Paragraph("As on : " + day.strftime("%d-%m-%Y"), sub),
    ]
    rows = [
        [cell("Account", True), cell("Debit Bal. (Rs.)", True), cell("Credit Bal. (Rs.)", True)]
    ]
    for account in snapshot["accounts"]:
        rows.append(
            [
                cell(account["name"]),
                indian_amount(account["debit"]),
                indian_amount(account["credit"]),
            ]
        )
    rows.append(
        [
            cell("Total", True),
            indian_amount(snapshot["debit_total"]),
            indian_amount(snapshot["credit_total"]),
        ]
    )
    width = A4[0] - 88
    table = LongTable(rows, colWidths=[width - 220, 110, 110], repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf0f7")),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 1), (-1, -1), 9),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#cad6e1")),
                ("LINEABOVE", (0, -1), (-1, -1), 0.7, colors.HexColor("#173b60")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f7f9fc")]),
                ("NOSPLIT", (0, -2), (-1, -1)),
            ]
        )
    )
    story = [
        table,
        Spacer(1, 12),
        Paragraph(f"{snapshot['account_count']} accounts | Amounts in INR", sub),
    ]

    def footer(canvas: Any, document: Any) -> None:
        canvas.saveState()
        y = A4[1] - 38
        for paragraph in header:
            _, height = paragraph.wrap(width, 100)
            paragraph.drawOn(canvas, 44, y - height)
            y -= height + 3
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#586b7f"))
        canvas.drawString(38, 25, "H.S. Traders | Group closing balances")
        canvas.drawRightString(A4[0] - 38, 25, f"Page {document.page}")
        canvas.restoreState()

    SimpleDocTemplate(
        str(path), pagesize=A4, leftMargin=38, rightMargin=38, topMargin=138, bottomMargin=42
    ).build(story, onFirstPage=footer, onLaterPages=footer)
