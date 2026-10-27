from datetime import datetime
from pathlib import Path

from app.domains.documents.models import DocumentRecord, natural_document_sort_key


def document(category: str, relative_path: str) -> DocumentRecord:
    path = Path(relative_path)
    return DocumentRecord(
        file_id=relative_path,
        category=category,
        file_name=path.name,
        relative_path=relative_path,
        size_bytes=1,
        modified_at=datetime.now().astimezone(),
        root_index=0,
        path=path,
    )


def test_natural_sort_uses_category_prefix_number_then_folder_name() -> None:
    records = [
        document("debit_notes", "Zeta/DN 2.pdf"),
        document("bills", "North/BILL 10.pdf"),
        document("bills", "North/BILL 2.pdf"),
        document("credit_notes", "CN 1.pdf"),
        document("bills", "South/ALPHA 1.pdf"),
    ]

    ordered = sorted(records, key=natural_document_sort_key)

    assert [record.relative_path for record in ordered] == [
        "South/ALPHA 1.pdf",
        "North/BILL 2.pdf",
        "North/BILL 10.pdf",
        "CN 1.pdf",
        "Zeta/DN 2.pdf",
    ]
