"""PATCH /api/projects/{code}/quote/lines/{line_id} - edit cost, margin or quantity; the correction is recorded.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from cbc.modules.extraction.api import feedback
from cbc.modules.ops.api import audit
from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.api import quote as quote_service
from cbc.modules.quoting.domain.quotes import QuoteLineUpdate
from cbc.modules.quoting.infrastructure.collections import estimate_lines
from cbc.shared.auth import Actor
from cbc.shared.mongo import oid, serialise

router = APIRouter(prefix="/api/projects/{code}/quote", tags=["quote"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.patch("/lines/{line_id}")
async def update_line(
    code: str, line_id: str, body: QuoteLineUpdate, actor: Actor
) -> dict:
    project = await load(code)
    line = await estimate_lines().find_one({"_id": oid(line_id), "projectId": project["_id"]})
    if not line:
        raise HTTPException(404, "quote line not found")

    changes = body.model_dump(exclude_unset=True)
    reason = changes.pop("overrideReason", None)
    if not changes:
        return {"line": serialise(line), "totals": await quote_service.persist(project)}

    override = {
        "at": _now(),
        "by": actor,
        "before": {key: line.get(key) for key in changes},
        "after": changes,
        "reason": reason,
    }
    # FR-13: what the copilot proposed, what the estimator chose instead, and
    # how confident it had been. Recorded before the write, so `before` is still
    # the copilot's value rather than the correction.
    await feedback.record_edits(
        bid_request_id=project["_id"],
        changes=changes,
        before=line,
        actor=actor,
        estimate_line_id=line["_id"],
        reason=reason,
    )

    update: dict[str, Any] = {**changes, "updatedAt": _now()}
    if "margin" in changes:
        update["marginOverridden"] = True
        update["overrideReason"] = reason

    await estimate_lines().update_one(
        {"_id": line["_id"]}, {"$set": update, "$push": {"overrides": override}}
    )
    await audit.record(
        "quote.line_edit",
        actor,
        {"projectId": project["_id"], "quoteLineId": line["_id"]},
        before=override["before"],
        after=changes,
        note=reason,
    )

    totals = await quote_service.persist(project)
    return {"line": serialise(await estimate_lines().find_one({"_id": line["_id"]})), "totals": totals}
