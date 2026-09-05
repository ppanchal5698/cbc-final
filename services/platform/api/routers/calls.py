"""Calls, notes and RFIs logged against a bid.

Phase 5 of the CBC process is judgment: reuse, direct equals, and raising RFIs
before finalising. Those conversations happen on the phone and then evaporate.
Logging them against the estimate is how they survive - the note travels with the
bid, and an estimator months later can see why a line reads the way it does.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from cbc.db import db, oid, serialise
from cbc.http.deps import Actor
from cbc.schemas import CallCreate
from cbc.http.projects_access import load
from cbc.services import audit

router = APIRouter(prefix="/api/projects/{code}/calls", tags=["calls"])

KIND_LABEL = {"call": "Call", "note": "Note", "rfi": "RFI"}


@router.get("")
async def list_calls(code: str, limit: int = Query(default=100, le=500)) -> dict:
    project = await load(code)
    entries = (
        await db.calls.find({"projectId": project["_id"]})
        .sort("createdAt", -1)
        .to_list(limit)
    )
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.get("kind", "call")] = counts.get(entry.get("kind", "call"), 0) + 1

    open_rfis = await db.calls.count_documents(
        {
            "projectId": project["_id"],
            "kind": "rfi",
            "$or": [{"resolvedAt": None}, {"resolvedAt": {"$exists": False}}],
        }
    )

    return {
        "calls": serialise(entries),
        "count": len(entries),
        "counts": counts,
        "openRfis": open_rfis,
    }


@router.post("", status_code=201)
async def log_call(code: str, body: CallCreate, actor: Actor) -> dict:
    project = await load(code)

    document = {
        **body.model_dump(exclude_none=True),
        "projectId": project["_id"],
        "who": actor,
        "createdAt": datetime.now(timezone.utc),
    }
    result = await db.calls.insert_one(document)
    document["_id"] = result.inserted_id

    await audit.record(
        f"call.{body.kind}",
        actor,
        {"projectId": project["_id"], "callId": result.inserted_id},
        after=body.text[:200],
        note=body.ref,
    )
    return serialise(document)


@router.post("/{call_id}/resolve")
async def resolve_rfi(code: str, call_id: str, actor: Actor) -> dict:
    """Close an RFI once the architect or GC has answered."""
    project = await load(code)
    entry = await db.calls.find_one({"_id": oid(call_id), "projectId": project["_id"]})
    if not entry:
        raise HTTPException(404, "note not found")
    if entry.get("kind") != "rfi":
        raise HTTPException(400, "only an RFI can be resolved")

    await db.calls.update_one(
        {"_id": entry["_id"]},
        {"$set": {"resolvedAt": datetime.now(timezone.utc), "resolvedBy": actor}},
    )
    await audit.record(
        "call.rfi_resolved", actor, {"projectId": project["_id"], "callId": entry["_id"]}
    )
    return serialise(await db.calls.find_one({"_id": entry["_id"]}))


@router.delete("/{call_id}", status_code=204)
async def delete_call(code: str, call_id: str, actor: Actor) -> None:
    project = await load(code)
    entry = await db.calls.find_one({"_id": oid(call_id), "projectId": project["_id"]})
    if not entry:
        raise HTTPException(404, "note not found")

    await db.calls.delete_one({"_id": entry["_id"]})
    await audit.record(
        "call.delete",
        actor,
        {"projectId": project["_id"], "callId": entry["_id"]},
        before=entry.get("text", "")[:200],
    )
