"""Line items - the extraction & entry screen.

This is where the estimator checks Claude's reading against the drawing and
either confirms it, corrects it, or throws it out. Every confirmation records who
made it, so a line's state is always attributable.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Response

from cbc.db import db
from cbc.shared.mongo import oid, serialise
from cbc.shared.auth import Actor
from cbc.schemas import BulkAction, LineItemCreate, LineItemUpdate
from cbc.http.projects_access import load
from cbc.http.pipeline_jobs import enqueue_pipeline
from cbc.persistence import repos
from cbc.modules.ops.api import audit
from cbc.services import feedback, sync
from cbc.services.quote import MAX_QUOTE_LINES

router = APIRouter(prefix="/api/projects/{code}/line-items", tags=["line-items"])

FILTERS = {
    "all": {},
    "needs_look": {"status": "needs_look"},
    "duplicate": {"status": "duplicate"},
    "by_hand": {"status": "by_hand"},
    "clear": {"status": "clear"},
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.get("")
async def list_line_items(
    code: str, filter: str = "all", alternate: str | None = None
) -> dict[str, Any]:
    project = await load(code)
    if filter not in FILTERS:
        raise HTTPException(400, f"unknown filter {filter!r}; try {sorted(FILTERS)}")

    # alternate="" selects the base bid explicitly; omitting it shows everything.
    query: dict[str, Any] = {"projectId": project["_id"], **FILTERS[filter]}
    if alternate is not None:
        query["alternateGroup"] = alternate or None
    items = await db.line_items.find(query).sort([("mark", 1), ("createdAt", 1)]).to_list(MAX_QUOTE_LINES)

    counts_raw = await db.line_items.aggregate(
        [{"$match": {"projectId": project["_id"]}}, {"$group": {"_id": "$status", "n": {"$sum": 1}}}]
    ).to_list(20)
    counts = {row["_id"]: row["n"] for row in counts_raw}

    return {
        "lineItems": serialise(items),
        "counts": {
            "all": sum(counts.values()),
            "needs_look": counts.get("needs_look", 0),
            "duplicate": counts.get("duplicate", 0),
            "by_hand": counts.get("by_hand", 0),
            "clear": counts.get("clear", 0),
        },
    }


@router.post("", status_code=201)
async def add_line_item(code: str, body: LineItemCreate, actor: Actor) -> dict:
    """Add something the drawings do not carry. Confirmed on arrival - a human typed it."""
    project = await load(code)
    openings = await repos.for_project(db.line_items, project, actor)

    payload = body.model_dump(exclude_none=True)
    mark = payload.get("mark") or payload.get("doorNumber")
    document = {
        **payload,
        "projectId": project["_id"],
        "bidRequestId": project["_id"],
        "mark": mark,
        "doorNumber": str(mark) if mark else None,
        "status": "by_hand",
        "addedByHand": True,
        "confidence": 1.0,
        "flags": [],
        "evidence": {"note": f"Added by hand by {actor}"},
        "confirmedBy": actor,
        "confirmedAt": _now(),
    }
    result = await openings.insert(document)
    document["_id"] = result.inserted_id

    await audit.record(
        "line_item.add_by_hand",
        actor,
        {"projectId": project["_id"], "lineItemId": result.inserted_id},
        after=body.description,
    )
    await feedback.record(
        bid_request_id=project["_id"],
        event_type="lineAdded",
        actor=actor,
        opening_id=result.inserted_id,
        corrected={"description": body.description, "mark": mark},
    )
    return serialise(document)


@router.patch("/{item_id}")
async def update_line_item(
    code: str, item_id: str, body: LineItemUpdate, actor: Actor
) -> dict:
    project = await load(code)
    item = await db.line_items.find_one({"_id": oid(item_id), "projectId": project["_id"]})
    if not item:
        raise HTTPException(404, "line item not found")

    changes = body.model_dump(exclude_none=True)
    if not changes:
        return serialise(item)

    edit = {
        "at": _now(),
        "by": actor,
        "before": {key: item.get(key) for key in changes},
        "after": changes,
    }
    await db.line_items.update_one(
        {"_id": item["_id"]},
        {"$set": {**changes, "updatedAt": _now()}, "$push": {"edits": edit}},
    )
    await audit.record(
        "line_item.edit",
        actor,
        {"projectId": project["_id"], "lineItemId": item["_id"]},
        before=edit["before"],
        after=changes,
    )
    await feedback.record_edits(
        bid_request_id=project["_id"],
        actor=actor,
        opening_id=item["_id"],
        before=edit["before"],
        changes=changes,
    )
    return serialise(await db.line_items.find_one({"_id": item["_id"]}))


@router.post("/{item_id}/confirm")
async def confirm_line_item(code: str, item_id: str, actor: Actor) -> dict:
    """Keep as is. The estimator has looked at the drawing and agrees."""
    project = await load(code)
    item = await db.line_items.find_one({"_id": oid(item_id), "projectId": project["_id"]})
    if not item:
        raise HTTPException(404, "line item not found")

    await db.line_items.update_one(
        {"_id": item["_id"]},
        {"$set": {"status": "clear", "confirmedBy": actor, "confirmedAt": _now()}},
    )
    await audit.record(
        "line_item.confirm", actor, {"projectId": project["_id"], "lineItemId": item["_id"]}
    )
    return serialise(await db.line_items.find_one({"_id": item["_id"]}))


@router.post("/confirm-all")
async def confirm_all(code: str, actor: Actor) -> dict:
    """Confirm everything still flagged for review, in one action."""
    project = await load(code)
    result = await db.line_items.update_many(
        {"projectId": project["_id"], "status": {"$in": ["needs_look", "duplicate"]}},
        {"$set": {"status": "clear", "confirmedBy": actor, "confirmedAt": _now()}},
    )
    await audit.record(
        "line_item.confirm_all",
        actor,
        {"projectId": project["_id"]},
        after={"confirmed": result.modified_count},
    )
    return {"confirmed": result.modified_count}


@router.post("/bulk")
async def bulk_action(code: str, body: BulkAction, actor: Actor) -> dict:
    """Confirm or remove a selection in one action.

    Same audit shape as the single-item paths, so a bulk confirm is as traceable
    as an individual one - it records how many, and which.
    """
    project = await load(code)
    ids = [oid(item_id) for item_id in body.ids]
    query = {"_id": {"$in": ids}, "projectId": project["_id"]}

    if body.action == "confirm":
        result = await db.line_items.update_many(
            query,
            {"$set": {"status": "clear", "confirmedBy": actor, "confirmedAt": _now()}},
        )
        affected = result.modified_count
    else:
        result = await db.line_items.delete_many(query)
        affected = result.deleted_count

    await audit.record(
        f"line_item.bulk_{body.action}",
        actor,
        {"projectId": project["_id"]},
        after={"requested": len(body.ids), "affected": affected},
    )
    return {"action": body.action, "requested": len(body.ids), "affected": affected}


@router.post("/{item_id}/resolve-duplicate")
async def resolve_duplicate(
    code: str, item_id: str, actor: Actor, keep: str = Body(embed=True, default="one")
) -> dict:
    """Keep one reading of a duplicated line, or keep both as separate lines."""
    project = await load(code)
    item = await db.line_items.find_one({"_id": oid(item_id), "projectId": project["_id"]})
    if not item:
        raise HTTPException(404, "line item not found")
    if keep not in ("one", "both"):
        raise HTTPException(400, "keep must be 'one' or 'both'")

    if keep == "one" and item.get("duplicateOf"):
        await db.line_items.delete_one({"_id": item["_id"]})
        await audit.record(
            "line_item.duplicate_dropped",
            actor,
            {"projectId": project["_id"], "lineItemId": item["_id"]},
        )
        return {"kept": "one", "removed": str(item["_id"])}

    await db.line_items.update_one(
        {"_id": item["_id"]},
        {
            "$set": {
                "status": "clear",
                "duplicateOf": None,
                "confirmedBy": actor,
                "confirmedAt": _now(),
            }
        },
    )
    await audit.record(
        "line_item.duplicate_kept",
        actor,
        {"projectId": project["_id"], "lineItemId": item["_id"]},
        after=keep,
    )
    return {"kept": keep, "lineItem": serialise(await db.line_items.find_one({"_id": item["_id"]}))}


@router.delete("/{item_id}", status_code=204, response_class=Response)
async def delete_line_item(code: str, item_id: str, actor: Actor) -> Response:
    project = await load(code)
    item = await db.line_items.find_one({"_id": oid(item_id), "projectId": project["_id"]})
    if not item:
        raise HTTPException(404, "line item not found")

    await db.line_items.delete_one({"_id": item["_id"]})
    await audit.record(
        "line_item.delete",
        actor,
        {"projectId": project["_id"], "lineItemId": item["_id"]},
        before=item.get("description"),
    )
    return Response(status_code=204)


@router.post("/rerun")
async def rerun_extraction(code: str, actor: Actor) -> dict:
    """Ask Claude to read the drawings again.

    Confirmed lines and hand-added lines are written down to disk first, so the
    re-run reconciles against the estimator's decisions instead of overwriting them.
    """
    project = await load(code)
    await sync.export_line_items(project)
    job = await enqueue_pipeline("rerun_extraction", project["_id"], actor=actor)
    return {"job": serialise(job)}


@router.post("/continue-to-quote")
async def continue_to_quote(code: str, actor: Actor) -> dict:
    """Phase boundary: push confirmed openings down to disk and enqueue pricing."""
    project = await load(code)

    outstanding = await db.line_items.count_documents(
        {"projectId": project["_id"], "status": "needs_look"}
    )
    await sync.export_line_items(project)

    job = await enqueue_pipeline("match_and_price", project["_id"], actor=actor)
    await audit.record(
        "project.continue_to_quote",
        actor,
        {"projectId": project["_id"]},
        note=f"{outstanding} item(s) still flagged at hand-off",
    )
    return {"job": serialise(job), "stillFlagged": outstanding}
