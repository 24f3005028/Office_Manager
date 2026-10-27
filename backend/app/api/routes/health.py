from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request) -> dict[str, object]:
    database_ok = request.app.state.database.ping()
    worker = request.app.state.worker
    return {
        "status": "ok" if database_ok else "degraded",
        "database": "ok" if database_ok else "error",
        "worker": "running" if worker.running else "stopped",
    }
