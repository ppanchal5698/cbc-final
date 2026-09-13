"""DELETE /api/projects/{code}/line-items/{item_id} - throw an opening out.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from cbc.modules.extraction.infrastructure.collections import openings
from cbc.modules.ops.api import audit
from cbc.modules.projects.api.lookup import load
from cbc.shared.auth import Actor
from cbc.shared.mongo import oid

router = APIRouter(prefix="/api/projects/{code}/line-items", tags=["line-items"])


@router.delete("/{item_id}", status_code=204, response_class=Response)
async def delete_line_item(code: str, item_id: str, actor: Actor) -> Response:
    project = await load(code)
    item = await openings().find_one({"_id": oid(item_id), "projectId": project["_id"]})
    if not item:
        raise HTTPException(404, "line item not found")

    await openings().delete_one({"_id": item["_id"]})
    await audit.record(
        "line_item.delete",
        actor,
        {"projectId": project["_id"], "lineItemId": item["_id"]},
        before=item.get("description"),
    )
    return Response(status_code=204)
