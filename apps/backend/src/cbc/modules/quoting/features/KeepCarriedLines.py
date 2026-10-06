"""POST /api/projects/{code}/quote/carried/keep - the lines carried from a prior bid apply to this one.
"""
from __future__ import annotations

from fastapi import APIRouter

from cbc.modules.ops.api import audit
from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.api import lines
from cbc.shared.auth import Actor

router = APIRouter(prefix="/api/projects/{code}/quote", tags=["quote"])


@router.post("/carried/keep")
async def keep_carried(code: str, actor: Actor) -> dict:
    project = await load(code)
    kept = await lines.keep_carried(project["_id"])
    await audit.record(
        "quote.carried_kept",
        actor,
        {"projectId": project["_id"]},
        after={"lines": kept, "from": project.get("templateSourceCode")},
    )
    return {"kept": kept}
