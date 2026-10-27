from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from app.api.schemas import DocumentCategory, DocumentMetadataResponse

router = APIRouter(prefix="/documents", tags=["documents"])

_DOCUMENT_TYPE_ALIASES = {
    "bill": "bills",
    "bills": "bills",
    "credit_note": "credit_notes",
    "credit_notes": "credit_notes",
    "debit_note": "debit_notes",
    "debit_notes": "debit_notes",
}


def _parse_categories(category: str | None, document_types: str | None) -> tuple[str, ...] | None:
    if category:
        values = [category]
    elif document_types:
        values = [item.strip() for item in document_types.split(",") if item.strip()]
    else:
        return None
    normalized: list[str] = []
    for value in values:
        try:
            mapped = _DOCUMENT_TYPE_ALIASES[value.casefold()]
        except KeyError as exc:
            raise ValueError(f"Unknown document category: {value}") from exc
        if mapped not in normalized:
            normalized.append(mapped)
    return tuple(normalized)


@router.get("", response_model=list[DocumentMetadataResponse])
def list_documents(
    request: Request,
    category: DocumentCategory | None = None,
    document_types: str | None = Query(default=None),
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> list[DocumentMetadataResponse]:
    effective_start = start_date or date_from
    effective_end = end_date or date_to
    try:
        categories = _parse_categories(category, document_types)
        documents = request.app.state.document_service.list_documents(
            start_date=effective_start,
            end_date=effective_end,
            categories=categories,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [
        DocumentMetadataResponse.model_validate(document.safe_metadata()) for document in documents
    ]


@router.get("/{file_id}/preview", response_model=DocumentMetadataResponse)
def preview_document(request: Request, file_id: str) -> DocumentMetadataResponse:
    document = request.app.state.document_service.get_preview(file_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentMetadataResponse.model_validate(document.safe_metadata())
