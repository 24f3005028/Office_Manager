from datetime import date, datetime
from pathlib import Path

from app.domains.documents.models import (
    DocumentRecord,
    natural_document_sort_key,
    resolve_document_local_date,
)


def document(
    category: str,
    file_name: str,
    *,
    day: int,
    root_index: int = 0,
    effective: bool = True,
) -> DocumentRecord:
    relative_path = f"root-{root_index}/{file_name}"
    return DocumentRecord(
        file_id=relative_path,
        category=category,
        file_name=file_name,
        relative_path=relative_path,
        size_bytes=1,
        modified_at=datetime(2026, 10, day, 12, 0).astimezone(),
        root_index=root_index,
        path=Path(relative_path),
        effective_date=date(2026, 10, day) if effective else None,
    )


def test_sort_is_date_then_category_then_root_then_natural_filename() -> None:
    records: list[DocumentRecord] = []
    for day in (25, 26, 27):
        records.extend(
            [
                document("debit_notes", f"DN-1 {day}.pdf", day=day, root_index=1),
                document("bills", f"HST-10 {day}.pdf", day=day, root_index=0),
                document("bills", f"HST-2 {day}.pdf", day=day, root_index=0),
                document("bills", f"HST-1 {day}.pdf", day=day, root_index=1),
                document("credit_notes", f"CN-1 {day}.pdf", day=day, root_index=1),
                document("credit_notes", f"CN-2 {day}.pdf", day=day, root_index=0),
                document("debit_notes", f"DN-10 {day}.pdf", day=day, root_index=0),
                document("debit_notes", f"DN-2 {day}.pdf", day=day, root_index=0),
            ]
        )

    ordered = sorted(records, key=natural_document_sort_key)

    expected: list[str] = []
    for day in (25, 26, 27):
        expected.extend(
            [
                f"HST-2 {day}.pdf",
                f"HST-10 {day}.pdf",
                f"HST-1 {day}.pdf",
                f"CN-2 {day}.pdf",
                f"CN-1 {day}.pdf",
                f"DN-2 {day}.pdf",
                f"DN-10 {day}.pdf",
                f"DN-1 {day}.pdf",
            ]
        )
    assert [record.file_name for record in ordered] == expected


def test_resolved_date_defaults_to_the_local_file_date() -> None:
    record = document("bills", "HST-1.pdf", day=26, effective=False)

    assert record.effective_date == date(2026, 10, 26)
    assert resolve_document_local_date(record) == date(2026, 10, 26)
