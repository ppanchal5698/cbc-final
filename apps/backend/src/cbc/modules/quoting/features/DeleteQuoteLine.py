"""DELETE /api/projects/{code}/quote/lines/{line_id} - remove a line; answers 200 with the new totals.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from cbc.modules.ops.api import audit
from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.api import priced_lines
from cbc.modules.quoting.api import quote as quote_service
from cbc.modules.quoting.infrastructure.collections import estimate_lines
from cbc.shared.auth import Actor
from cbc.shared.mongo import oid

router = APIRouter(prefix="/api/projects/{code}/quote", tags=["quote"])


@router.delete("/lines/{line_id}")
async def delete_line(code: str, line_id: str, actor: Actor) -> dict:
    project = await load(code)
    line = await estimate_lines().find_one({"_id": oid(line_id), "projectId": project["_id"]})
    if not line:
        raise HTTPException(404, "quote line not found")

    await estimate_lines().delete_one({"_id": line["_id"]})
    await audit.record(
        "quote.line_delete",
        actor,
        {"projectId": project["_id"], "quoteLineId": line["_id"]},
        before=line.get("description"),
    )
    totals = await quote_service.persist(project)
    # Persist deliberate deletions, including the last row, before a later export
    # mistakes the remaining artifact for an unimported pricing pass.
    await priced_lines.export_quote_lines(project, allow_empty=True)
    return {"totals": totals}
