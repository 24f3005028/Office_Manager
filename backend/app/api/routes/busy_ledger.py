"""BUSY ledger Excel import and status endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, cast

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.api.schemas import (
    BusyLedgerCategoryStatus,
    BusyLedgerFileResult,
    BusyLedgerImportResponse,
    BusyLedgerSampleKey,
    BusyLedgerStatusResponse,
    DocumentCategory,
)
from app.domains.busy_ledger.parser import SUPPORTED_WORKBOOK_SUFFIXES, BusyLedgerError
from app.domains.busy_ledger.service import BusyImportSummary

router = APIRouter(prefix="/busy-ledger", tags=["busy ledger"])

_CATEGORIES: tuple[DocumentCategory, ...] = ("bills", "credit_notes", "debit_notes")


def _category(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip().casefold()
    if normalized not in _CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Unknown document category: {value}")
    return normalized


def _import_response(summary: BusyImportSummary) -> BusyLedgerImportResponse:
    files = [
        BusyLedgerFileResult(
            filename=item.filename,
            category=cast(DocumentCategory, item.category) if item.category else None,
            detected_headers=item.detected_headers,
            rows_found=item.rows_found,
            rows_imported=item.rows_imported,
            sample_keys=[
                BusyLedgerSampleKey(
                    category=cast(DocumentCategory, row.category),
                    raw_voucher_no=row.raw_voucher_no,
                    canonical_series=row.canonical_series,
                    fy=row.fy,
                    serial=row.serial,
                    voucher_date=row.voucher_date,
                    party_name=row.party_name,
                )
                for row in item.sample_rows
            ],
            warnings=list(item.warnings),
            min_date=item.min_date,
            max_date=item.max_date,
            deleted=item.deleted,
        )
        for item in summary.files
    ]
    return BusyLedgerImportResponse(
        dry_run=summary.dry_run,
        files=files,
        rows_found=summary.rows_found,
        rows_imported=summary.rows_imported,
        warnings=list(summary.warnings),
    )


@router.post("/import", response_model=BusyLedgerImportResponse)
async def import_busy_ledger(
    request: Request,
    file: Annotated[UploadFile | None, File()] = None,
    dry_run: Annotated[bool, Form()] = False,
    category: Annotated[str | None, Form()] = None,
) -> BusyLedgerImportResponse:
    """Import an uploaded BUSY export or every workbook in the app-owned inbox."""

    selected_category = _category(category)
    service = request.app.state.busy_ledger_service
    try:
        if file is not None:
            filename = Path(file.filename or "busy-ledger.xlsx").name
            if Path(filename).suffix.casefold() not in SUPPORTED_WORKBOOK_SUFFIXES:
                raise HTTPException(
                    status_code=400,
                    detail="Upload a BUSY Excel export (.xlsx, .xlsm or .xls).",
                )
            content = await file.read()
            saved_path = service.save_upload(filename, content)
            summary = service.import_workbooks(
                [saved_path], category=selected_category, dry_run=dry_run
            )
        else:
            summary = service.import_inbox(
                category=selected_category, dry_run=dry_run
            )
    except BusyLedgerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _import_response(summary)


@router.get("/status", response_model=BusyLedgerStatusResponse)
def busy_ledger_status(request: Request) -> BusyLedgerStatusResponse:
    status = request.app.state.busy_ledger_service.status()
    indexed = {item.category: item for item in status.categories}
    categories = [
        BusyLedgerCategoryStatus(
            category=category,
            total_vouchers=indexed[category].total_vouchers if category in indexed else 0,
            min_date=indexed[category].min_date if category in indexed else None,
            max_date=indexed[category].max_date if category in indexed else None,
        )
        for category in _CATEGORIES
    ]
    return BusyLedgerStatusResponse(
        last_sync_at=status.last_sync_at,
        last_sync_filename=status.last_sync_filename,
        total_vouchers=status.total_vouchers,
        categories=categories,
    )
