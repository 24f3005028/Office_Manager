"""Print layout regression: fiscal-year bill references are not report dates."""

from datetime import date
from decimal import Decimal

import pymupdf
from app.domains.mobile.all_outstanding import verify_all_pdf
from app.domains.mobile.outstanding_pdf import render_all_pdf


def test_print_pdf_repeats_headers_and_keeps_all_account_totals(tmp_path):
    accounts = []
    for index in range(50):
        accounts.append(
            {
                "party_name": f"PARTY {index} & TEXTILES",
                "pending_amount": "100.00",
                "bills": [
                    {
                        "bill_number": f"HST/26-27/{1000 + index}",
                        "date": "2026-11-01",
                        "reference_amount": "200.00",
                        "pending_amount": "100.00",
                        "due_date": "2026-11-01",
                        "due_days": 5,
                        "discount": "2.5",
                        "broker": "EXAMPLE BROKER",
                    }
                ],
            }
        )
    snapshot = {
        "scope": "all",
        "format": "new1",
        "start_date": "2025-01-16",
        "as_of": "2026-11-06",
        "layout": "bills",
        "accounts": accounts,
        "account_count": 50,
        "bill_count": 50,
        "pending_amount": str(sum((Decimal(a["pending_amount"]) for a in accounts), Decimal(0))),
        "company_header": ["H.S. TRADERS"],
    }
    output = tmp_path / "all.pdf"
    render_all_pdf(snapshot, output)
    result = verify_all_pdf(output, snapshot, date(2026, 11, 6))
    assert result["pages"] > 1
    with pymupdf.open(output) as pdf:
        assert all(
            "Bills Receivable" in page.get_text() and "DISCOUNT" in page.get_text() for page in pdf
        )
        assert "Grand Total" in pdf[-1].get_text()
