"""Health endpoint for the modular monolith."""
from __future__ import annotations

from fastapi import APIRouter

from cbc.bootstrap.config import settings

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "cbc-backend",
        "database": "deferred",
        "storageRoot": str(settings.storage_root),
        "sends": "disabled by design (NFR-1)",
        "phase": "0-skeleton",
    }
