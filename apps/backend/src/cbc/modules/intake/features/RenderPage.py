"""GET /api/projects/{code}/documents/{document_id}/page/{page_number} - one page as a PNG.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import Response as PlainResponse

from cbc.modules.intake.infrastructure.document_access import find_on_bid
from cbc.modules.intake.infrastructure import pdf
from cbc.shared import storage

router = APIRouter(prefix="/api/projects/{code}/documents", tags=["documents"])


@router.get("/{document_id}/page/{page_number}")
async def get_page(code: str, document_id: str, page_number: int, dpi: int = 110) -> Response:
    """A rendered page image, for viewers that cannot run pdf.js."""
    document = await find_on_bid(code, document_id)

    try:
        image = await asyncio.to_thread(
            pdf.render_page, storage.absolute(document["path"]), page_number, dpi
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    return PlainResponse(
        await asyncio.to_thread(image.read_bytes),
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=86400"},
    )
