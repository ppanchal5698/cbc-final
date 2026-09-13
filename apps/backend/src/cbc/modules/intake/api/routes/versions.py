"""Addendum version snapshots — interim structure only (Matrix 4.1 / FR-14)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pymongo.errors import DuplicateKeyError

from cbc.db import db
from cbc.shared.mongo import serialise
from cbc.shared.auth import Actor
from cbc.schemas import VersionCreate
from cbc.modules.projects.api.lookup import load
from cbc.modules.ops.api.jobs import enqueue_pipeline, reserve
from cbc.persistence import versioning
from cbc.modules.ops.api import audit

router = APIRouter(prefix="/api/projects/{code}", tags=["versions"])

PENDING_NOTE = (
    "How an addendum reconciles against the previous version, and whether an "
    "alternate inherits the base bid's confirmations, are still open questions "
    "(Matrix 4.1 / Open Item 11). Differences are flagged, never merged."
)


# A snapshot embeds whole documents, against MongoDB's 16 MB per-document limit.
# Silently keeping the first 5 000 would report a complete freeze of an incomplete
# bid - the one thing a version is for is being able to trust it later.
SNAPSHOT_LIMIT = 5000


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _snapshot_all(collection, project_id: Any, label: str) -> list[dict[str, Any]]:
    found = await collection.find({"projectId": project_id}).to_list(SNAPSHOT_LIMIT + 1)
    if len(found) > SNAPSHOT_LIMIT:
        raise ValueError(
            f"this bid has more than {SNAPSHOT_LIMIT} {label}, which is more than a "
            "version snapshot can hold. Snapshotting it would silently freeze an "
            "incomplete record."
        )
    return found


async def snapshot(project: dict[str, Any], reason: str, actor: str) -> dict[str, Any]:
    """Freeze the current line items and quote lines into a new version."""
    project_id = project["_id"]
    line_items = await _snapshot_all(db.line_items, project_id, "line items")
    quote_lines = await _snapshot_all(db.quote_lines, project_id, "quote lines")

    previous = await db.versions.find_one(
        {"projectId": project_id, "supersededByVersionId": None},
        sort=[("version", -1)],
    )
    document = {
        "projectId": project_id,
        "reason": reason,
        "createdAt": _now(),
        "createdBy": actor,
        "reconciled": False,
        # §3.26: a version is a link in a chain, not a loose document. The head
        # is the one nothing supersedes, which is what the specification indexes
        # for - rather than sorting by number and hoping.
        "previousVersionId": (previous or {}).get("_id"),
        "supersededByVersionId": None,
        "lockedAt": None,
        "status": "draft",
        "statusHistory": [],
        "approvedBy": None,
        "approvedAt": None,
        "lineItemCount": len(line_items),
        "quoteLineCount": len(quote_lines),
        "snapshot": {
            "lineItems": serialise(line_items),
            "quoteLines": serialise(quote_lines),
        },
    }

    # Read-then-write on the version number: two addenda uploaded together both
    # became version n+1, and the addendum diff then attached to whichever one
    # Mongo happened to return. `(projectId, version)` is unique now, so the loser
    # of the race is told to try again rather than quietly sharing a number.
    for _ in range(5):
        latest = await db.versions.find_one({"projectId": project_id}, sort=[("version", -1)])
        number = (latest or {}).get("version", 0) + 1
        document["version"] = number
        try:
            result = await db.versions.insert_one(document)
        except DuplicateKeyError:
            document.pop("_id", None)
            continue
        document["_id"] = result.inserted_id
        break
    else:
        raise ValueError("could not allocate a version number; try again")

    # Live lines belong to this version (spec: estimateLines.estimateVersionId).
    # Embedded snapshot stays as the immutable freeze for diffs until S3 fully
    # migrates readers off the blob.
    await db.quote_lines.update_many(
        {"projectId": project_id},
        {"$set": {"estimateVersionId": document["_id"]}},
    )
    await db.line_items.update_many(
        {"projectId": project_id},
        {"$set": {"estimateVersionId": document["_id"]}},
    )

    if previous is not None:
        # Sealing happens after the new version exists, so a crash between the two
        # leaves an unsealed predecessor rather than a chain pointing at nothing.
        await db.versions.update_one(
            {"_id": previous["_id"]},
            {"$set": versioning.supersede(previous, by_id=result.inserted_id, actor=actor)},
        )

    await db.projects.update_one({"_id": project_id}, {"$set": {"version": number}})
    await audit.record(
        "version.snapshot",
        actor,
        {"projectId": project_id, "versionId": result.inserted_id},
        after={"version": number, "reason": reason},
    )
    return document


@router.get("/versions")
async def list_versions(code: str) -> dict[str, Any]:
    project = await load(code)
    found = (
        await db.versions.find({"projectId": project["_id"]}, {"snapshot": 0})
        .sort("version", -1)
        .to_list(50)
    )
    unreconciled = await db.versions.count_documents(
        {"projectId": project["_id"], "reconciled": {"$ne": True}}
    )
    return {
        "versions": serialise(found),
        "current": project.get("version", 1),
        "unreconciled": unreconciled,
        "pending": PENDING_NOTE,
    }


@router.get("/versions/{version}")
async def get_version(code: str, version: int) -> dict[str, Any]:
    project = await load(code)
    found = await db.versions.find_one({"projectId": project["_id"], "version": version})
    if not found:
        raise HTTPException(404, f"version {version} not found")
    return serialise(found)


@router.post("/versions", status_code=201)
async def create_version(code: str, body: VersionCreate, actor: Actor) -> dict:
    project = await load(code)

    # Before the snapshot, not after it: a 409 raised from the enqueue below used
    # to leave a frozen version behind that no job would ever read.
    superseded = await reserve(project["_id"], "ingest_addendum") if body.documentId else None

    document = await snapshot(project, body.reason, actor)

    job = None
    if body.documentId:
        job = await enqueue_pipeline(
            "ingest_addendum",
            project["_id"],
            payload={
                "documentId": body.documentId,
                "version": document["version"],
                "reason": body.reason,
            },
            actor=actor,
        )

    return {
        "version": serialise({k: v for k, v in document.items() if k != "snapshot"}),
        "job": serialise(job) if job else None,
        "superseded": serialise(superseded) if superseded else None,
        "pending": PENDING_NOTE,
    }


@router.get("/versions/{version}/diff")
async def diff_version(code: str, version: int) -> dict[str, Any]:
    project = await load(code)
    stored = await db.versions.find_one({"projectId": project["_id"], "version": version})
    if not stored:
        raise HTTPException(404, f"version {version} not found")

    def key(item: dict[str, Any]) -> str:
        return str(item.get("mark") or item.get("description", ""))[:60]

    before = {key(i): i for i in stored["snapshot"]["lineItems"]}
    current = {
        key(i): i for i in await db.line_items.find({"projectId": project["_id"]}).to_list(5000)
    }

    watched = ("description", "size", "qty", "hwSet", "finish", "fireRating", "handing")
    changed = []
    for mark, now in current.items():
        was = before.get(mark)
        if not was:
            continue
        fields = [f for f in watched if str(was.get(f)) != str(now.get(f))]
        if fields:
            changed.append(
                {
                    "mark": mark,
                    "fields": fields,
                    "before": {f: was.get(f) for f in fields},
                    "after": {f: now.get(f) for f in fields},
                }
            )

    return {
        "version": version,
        "added": sorted(set(current) - set(before)),
        "removed": sorted(set(before) - set(current)),
        "changed": changed,
        "pending": PENDING_NOTE,
    }


@router.post("/versions/{version}/reconcile")
async def mark_reconciled(code: str, version: int, actor: Actor) -> dict:
    project = await load(code)
    stored = await db.versions.find_one({"projectId": project["_id"], "version": version})
    if stored is None:
        raise HTTPException(404, f"version {version} not found")
    try:
        versioning.guard_writable(stored)
    except versioning.VersionLocked as exc:
        # §3.26: a sealed version must never be written again. This handler used
        # to reach any version, including ones superseded months earlier.
        raise HTTPException(409, str(exc)) from exc

    result = await db.versions.update_one(
        {"projectId": project["_id"], "version": version, "lockedAt": None},
        {"$set": {"reconciled": True, "reconciledBy": actor, "reconciledAt": _now()}},
    )
    if not result.matched_count:
        raise HTTPException(409, f"version {version} was sealed while reconciling")

    await audit.record(
        "version.reconciled", actor, {"projectId": project["_id"]}, after={"version": version}
    )
    return {"version": version, "reconciled": True, "by": actor}
