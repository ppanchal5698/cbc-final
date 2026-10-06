"""PATCH /api/projects/{code}/quote/lines/{line_id} - edit cost, margin or quantity; the correction is recorded.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from cbc.modules.extraction.api import feedback
from cbc.modules.ops.api import audit
from cbc.modules.pricing.api import reference_library
from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.api import lines as lines_api
from cbc.modules.quoting.api import quote as quote_service
from cbc.modules.quoting.domain.quotes import OVERRIDE_REASONS, QuoteLineUpdate
from cbc.modules.quoting.infrastructure.collections import estimate_lines
from cbc.shared.auth import Actor
from cbc.shared.mongo import oid, serialise

router = APIRouter(prefix="/api/projects/{code}/quote", tags=["quote"])
log = logging.getLogger("cbc.quote")


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
    reason_code = changes.pop("overrideCode", None)
    if reason_code and not changes and line.get("marginOverridden"):
        # The reason for a margin already overridden (requirements 5.1): a code,
        # with the estimator's words when they gave some.
        said = {"overrideCode": reason_code, "overrideReason": reason or OVERRIDE_REASONS[reason_code]}
        await estimate_lines().update_one({"_id": line["_id"]}, {"$set": {**said, "updatedAt": _now()}})
        await audit.record("quote.override_reason", actor,
                           {"projectId": project["_id"], "quoteLineId": line["_id"]},
                           before={k: line.get(k) for k in said}, after=said)
        return {"line": serialise(await estimate_lines().find_one({"_id": line["_id"]})),
                "totals": await quote_service.persist(project)}
    if not changes:
        return {"line": serialise(line), "totals": await quote_service.persist(project)}
    if changes.get("cost") is not None and "costSource" not in changes:
        # A cost typed by hand is the estimator's, not the sheet the ladder priced
        # the line from: it kept saying "List x multiplier, Hager Price Book #18"
        # over a number nobody read off that book (NFR-3).
        changes["costSource"] = "MANUAL"
        changes.setdefault("costSourceDetail", f"entered by {actor}")

    # The estimator's words, else the reason code's (requirements 5.1).
    reason = reason or (OVERRIDE_REASONS[reason_code] if reason_code else None)
    override = {
        "at": _now(),
        "by": actor,
        "before": {key: line.get(key) for key in changes},
        "after": changes,
        "reason": reason,
        "code": reason_code,
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
        update["overrideCode"] = reason_code

    await estimate_lines().update_one(
        {"_id": line["_id"]},
        # An estimator who edits a line carried from a prior bid has looked at it.
        {"$set": update, "$push": {"overrides": override}, "$pull": {"flags": lines_api.CARRIED}},
    )
    await audit.record(
        "quote.line_edit",
        actor,
        {"projectId": project["_id"], "quoteLineId": line["_id"]},
        before=override["before"],
        after=changes,
        note=reason,
    )

    if changes.get("part") and "allegion_equal_needed" in (line.get("flags") or []):
        await _keep_equal(project, line, changes, actor)

    totals = await quote_service.persist(project)
    return {"line": serialise(await estimate_lines().find_one({"_id": line["_id"]})), "totals": totals}


async def _keep_equal(project: dict[str, Any], line: dict[str, Any], changes: dict[str, Any], actor: str) -> None:
    """FR-13: the equal an estimator names for an Allegion part is kept, so the next
    bid that specifies the part prices it. The line keeps the edit either way."""
    specified = await estimate_lines().find_one({"projectId": project["_id"], "lineKey": f"{line.get('lineKey')}:allegion"})
    if not specified or not specified.get("part"):
        return
    item = {"brand": specified.get("manufacturer"), "part": specified["part"],
            "equal_manufacturer": changes.get("manufacturer") or line.get("manufacturer") or "Hager",
            "equal_part": changes["part"], "named_by": actor, "named_at": _now().isoformat()}
    try:
        await asyncio.to_thread(reference_library.update_hardware_equals, items=[item], actor=actor)
    except Exception as exc:  # the edit stands; the equal waits for the next one
        log.warning("equal for %s not kept: %s", specified["part"], exc)
        return
    await estimate_lines().update_one({"_id": line["_id"]}, {"$pull": {"flags": "allegion_equal_needed"}})
