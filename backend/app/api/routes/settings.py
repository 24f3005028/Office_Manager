from __future__ import annotations

from typing import Literal, cast

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.folder_picker import FolderPickerUnavailableError, pick_folder

router = APIRouter(prefix="/settings", tags=["settings"])

DocumentCategory = Literal["bills", "credit_notes", "debit_notes"]


class DocumentRootsRequest(BaseModel):
    document_roots: dict[DocumentCategory, list[str]] = Field(default_factory=dict)


@router.get("")
def get_settings(request: Request) -> dict[str, object]:
    return {
        **cast(dict[str, object], request.app.state.workspace_settings.get()),
        **request.app.state.bridge_readiness.details(),
    }


@router.put("/document-roots")
async def update_document_roots(
    request: Request, payload: DocumentRootsRequest
) -> dict[str, object]:
    try:
        request.app.state.workspace_settings.update(payload.document_roots)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    root_paths = request.app.state.workspace_settings.root_paths()
    request.app.state.document_service.update_roots(root_paths)
    request.app.state.bridge_readiness.invalidate()
    await request.app.state.bridge_readiness.refresh()
    return get_settings(request)


@router.post("/pick-folder")
def pick_document_folder() -> dict[str, str]:
    try:
        return {"path": str(pick_folder())}
    except FolderPickerUnavailableError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
