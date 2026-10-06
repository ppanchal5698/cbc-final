"""POST /api/projects/{code}/quote/lines/{line_id}/close-matches/{index} - price a line at one of its close matches (FR-8).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from cbc.modules.extraction.api import feedback
from cbc.modules.ops.api import audit
from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.api import quote as quote_service
from cbc.modules.quoting.infrastructure.collections import estimate_lines
from cbc.shared.auth import Actor
from cbc.shared.mongo import oid, serialise

router = APIRouter(prefix="/api/projects/{code}/quote", tags=["quote"])

# What a person's choice settles: the line no longer waits on a pick, the model's or anyone's.
_SETTLED = ["ambiguous_match", "model_chose_match"]


@router.post("/lines/{line_id}/close-matches/{index}")
async def choose_close_match(code: str, line_id: str, index: int, actor: Actor) -> dict:
    project = await load(code)
    line = await estimate_lines().find_one({"_id": oid(line_id), "projectId": project["_id"]})
    if not line:
        raise HTTPException(404, "quote line not found")
    matches = line.get("closeMatches") or []
    if not 0 <= index < len(matches):
        raise HTTPException(404, "this line has no such close match")

    # Priced when the line was, through the same rung: the part, its cost and where
    # it came from move together, so the line stays traceable (NFR-3).
    chosen = {key: value for key, value in matches[index].items() if key != "label"}
    reason = f"chose a close match: {matches[index].get('label')}"
    before = {key: line.get(key) for key in chosen}
    now = datetime.now(timezone.utc)
    await feedback.record_edits(bid_request_id=project["_id"], changes=chosen, before=line, actor=actor,
                                estimate_line_id=line["_id"], reason=reason)
    await estimate_lines().update_one(
        {"_id": line["_id"]},
        {
            # The match is the estimator's now: the copilot's confidence no longer applies.
            "$set": {**chosen, "priceStatus": "PRICED", "matchConfidence": None, "updatedAt": now},
            # An estimator's edit, so a re-price keeps it like any other.
            "$push": {"overrides": {"at": now, "by": actor, "before": before, "after": chosen, "reason": reason}},
            "$pullAll": {"flags": _SETTLED},
        },
    )
    await audit.record("quote.close_match_chosen", actor, {"projectId": project["_id"], "quoteLineId": line["_id"]},
                       before=before, after=chosen, note=reason)
    totals = await quote_service.persist(project)
    return {"line": serialise(await estimate_lines().find_one({"_id": line["_id"]})), "totals": totals}
