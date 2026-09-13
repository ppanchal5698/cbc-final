"""GET /api/projects/{code}/documents/{document_id}/page/{page_number}/size - the frame every bbox is measured in.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter

from cbc.modules.intake.infrastructure.document_access import find_on_bid
from cbc.modules.intake.infrastructure import pdf
from cbc.shared import storage

router = APIRouter(prefix="/api/projects/{code}/documents", tags=["documents"])


@router.get("/{document_id}/page/{page_number}/size")
async def get_page_size(code: str, document_id: str, page_number: int) -> dict:
    """Page dimensions in PDF points - the frame every stored bbox is measured against."""
    document = await find_on_bid(code, document_id)
    return await asyncio.to_thread(
        pdf.page_size, storage.absolute(document["path"]), page_number
    )
