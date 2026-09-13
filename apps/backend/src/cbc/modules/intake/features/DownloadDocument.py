"""GET /api/projects/{code}/documents/{document_id}/file - the raw PDF.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from cbc.modules.intake.infrastructure.document_access import find_on_bid
from cbc.services import storage  # ponytail: legacy kernel; the file tree moves to shared/ in Phase 4

router = APIRouter(prefix="/api/projects/{code}/documents", tags=["documents"])


@router.get("/{document_id}/file")
async def get_file(code: str, document_id: str) -> FileResponse:
    """Serve the raw PDF so the reviewer sees the actual drawing, not a re-rendering."""
    document = await find_on_bid(code, document_id)

    path = storage.absolute(document["path"])
    if not path.exists():
        raise HTTPException(410, f"file missing on disk: {document['path']}")

    return FileResponse(
        path,
        media_type="application/pdf",
        filename=document["filename"],
        headers={"Cache-Control": "private, max-age=3600"},
    )
