"""DELETE /api/projects/{code}/documents/{document_id} - detach a document; the file stays.
"""
from __future__ import annotations

from fastapi import APIRouter, Response

from cbc.modules.intake.infrastructure.collections import documents
from cbc.modules.intake.infrastructure.document_access import find_on_bid
from cbc.modules.ops.api import audit
from cbc.shared.auth import Actor

router = APIRouter(prefix="/api/projects/{code}/documents", tags=["documents"])


@router.delete("/{document_id}", status_code=204, response_class=Response)
async def delete_document(code: str, document_id: str, actor: Actor) -> Response:
    """Detach a document from the bid. The file itself stays - raw uploads are immutable."""
    document = await find_on_bid(code, document_id)

    await documents().delete_one({"_id": document["_id"]})
    await audit.record(
        "document.delete",
        actor,
        {"projectId": document["projectId"], "documentId": document["_id"]},
        before=document.get("filename"),
        note="file retained on disk",
    )
    return Response(status_code=204)
