"""Projects - the bid record every other screen hangs off."""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from cbc.db import db
from cbc.shared.mongo import oid, serialise
from cbc.shared.auth import AdminActor, Actor
from cbc.schemas import ProjectCreate, ProjectUpdate
from cbc.modules.ops.api import audit
from cbc.services import storage, reuse

router = APIRouter(prefix="/api/projects", tags=["projects"])

STAGE_PROGRESS = {"intake": 0, "extraction": 33, "quote": 67, "proposal": 100}


async def next_code() -> str:
    """Allocate the next CBC-YYNNNN atomically."""
    prefix = storage.code_prefix()
    counter = await db.counters.find_one_and_update(
        {"_id": prefix},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    if counter["seq"] == 1:
        # First allocation under this prefix. The database may already carry codes
        # issued before the counter existed, so continue that series instead of
        # restarting on top of it. Costs one scan per prefix, once.
        highest = storage.highest_code_sequence(await db.projects.distinct("code"), prefix)
        if highest >= 1:
            counter = await db.counters.find_one_and_update(
                {"_id": prefix},
                {"$set": {"seq": highest + 1}},
                return_document=ReturnDocument.AFTER,
            )
    return f"{prefix}{counter['seq']:04d}"


async def load(code_or_id: str) -> dict[str, Any]:
    """Look a project up by code (CBC-260143), slug, or id - whatever the caller has."""
    query: dict[str, Any] = {"$or": [{"code": code_or_id}, {"slug": code_or_id}]}
    try:
        query["$or"].append({"_id": oid(code_or_id)})
    except ValueError:
        pass
    project = await db.projects.find_one(query)
    if not project:
        raise HTTPException(404, f"project not found: {code_or_id}")
    return project


async def _count_by_project(collection, ids: list[Any]) -> dict[Any, int]:
    rows = await collection.aggregate(
        [{"$match": {"projectId": {"$in": ids}}},
         {"$group": {"_id": "$projectId", "n": {"$sum": 1}}}]
    ).to_list(length=len(ids) + 1)
    return {row["_id"]: row["n"] for row in rows}


async def _decorate_many(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach the counts the board and stage bar render, for a whole page of bids.

    Five aggregations for the entire list, not six queries per bid. The board is
    the landing page and its cost used to grow linearly with the number of open
    bids - at the default limit that was three hundred sequential round trips.
    """
    if not projects:
        return []
    ids = [project["_id"] for project in projects]

    # Statuses and confirmations in one pass: `status` carries provenance
    # (`by_hand`) in the same field as review state, so a confirmed hand-added
    # line is not in the `clear` bucket. Confirmation is what "cleared" means to
    # an estimator, so count the thing that records it.
    status_rows = await db.line_items.aggregate(
        [
            {"$match": {"projectId": {"$in": ids}}},
            {
                "$group": {
                    "_id": {"projectId": "$projectId", "status": "$status"},
                    "n": {"$sum": 1},
                }
            },
        ]
    ).to_list(length=None)

    confirmed_rows = await db.line_items.aggregate(
        [
            {
                "$match": {
                    "projectId": {"$in": ids},
                    "confirmedAt": {"$exists": True, "$ne": None},
                }
            },
            {"$group": {"_id": "$projectId", "n": {"$sum": 1}}},
        ]
    ).to_list(length=None)

    counts: dict[Any, dict[str, int]] = {}
    confirmed = {row["_id"]: row["n"] for row in confirmed_rows}
    for row in status_rows:
        project_id, status = row["_id"]["projectId"], row["_id"]["status"]
        counts.setdefault(project_id, {})[status] = row["n"]

    quotes = {
        quote["projectId"]: quote
        for quote in await db.quotes.find({"projectId": {"$in": ids}}).to_list(len(ids) + 1)
    }
    # Newest first, so the first one seen per project is the current active job.
    active: dict[Any, dict[str, Any]] = {}
    for job in await db.jobs.find(
        {"projectId": {"$in": ids}, "status": {"$in": ["queued", "running"]}}
    ).sort("createdAt", -1).to_list(length=None):
        active.setdefault(job["projectId"], job)

    documents = await _count_by_project(db.documents, ids)
    calls = await _count_by_project(db.calls, ids)

    decorated = []
    for project in projects:
        project_id = project["_id"]
        by_status = counts.get(project_id, {})
        decorated.append(
            {
                **serialise(project),
                "counts": {
                    "total": sum(by_status.values()),
                    "clear": confirmed.get(project_id, 0),
                    "needsLook": by_status.get("needs_look", 0),
                    "duplicate": by_status.get("duplicate", 0),
                    "byHand": by_status.get("by_hand", 0),
                },
                "documentCount": documents.get(project_id, 0),
                "version": project.get("version", 1),
                "callCount": calls.get(project_id, 0),
                "quoteTotal": quotes.get(project_id, {}).get("grandTotal"),
                "activeJob": serialise(active[project_id]) if project_id in active else None,
            }
        )
    return decorated


async def _decorate(project: dict[str, Any]) -> dict[str, Any]:
    """One bid, through the same code path as the board - no second implementation."""
    return (await _decorate_many([project]))[0]


@router.get("")
async def list_projects(
    stage: str | None = None,
    q: str | None = None,
    limit: int = Query(default=50, le=200),
) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if stage:
        query["stage"] = stage
    if q:
        needle = re.escape(q)  # user input, not a pattern
        query["$or"] = [
            {"name": {"$regex": needle, "$options": "i"}},
            {"code": {"$regex": needle, "$options": "i"}},
            {"gc": {"$regex": needle, "$options": "i"}},
            {"brand": {"$regex": needle, "$options": "i"}},
        ]

    projects = await db.projects.find(query).sort("createdAt", -1).to_list(length=limit)
    return {"projects": await _decorate_many(projects)}


@router.post("", status_code=201)
async def create_project(body: ProjectCreate, actor: Actor) -> dict[str, Any]:
    code = await next_code()

    # Unless the bid says otherwise, the installation default decides. False out
    # of the box: the gated flow is what CLAUDE.md describes, and autopilot prices
    # openings nobody has checked.
    autopilot = body.autopilot
    if autopilot is None:
        pipeline = await db.settings.find_one({"_id": "pipeline"}) or {}
        autopilot = bool(pipeline.get("autopilotDefault", False))

    slug = storage.slugify(body.name)
    if await db.projects.find_one({"slug": slug}):
        slug = f"{slug}_{code.lower().replace('-', '_')}"

    now = datetime.now(timezone.utc)
    # Matrix 3.0: default one-off when the create form omits mode.
    mode = body.mode or "one_off"
    alternates = [a.strip() for a in (body.bidAlternates or []) if a and str(a).strip()]
    from cbc.persistence import repos

    org_id = await repos.org_id_for(None)
    doc = {
        **body.model_dump(exclude_none=True, exclude={"bidDue", "mode", "bidAlternates"}),
        "bidDue": datetime.combine(body.bidDue, datetime.min.time(), tzinfo=timezone.utc)
        if body.bidDue
        else None,
        "mode": mode,
        "bidAlternates": alternates,
        "intakeChannel": body.intakeChannel or "manual",
        "orgId": org_id,
        "code": code,
        "slug": slug,
        "autopilot": autopilot,
        "stage": "intake",
        "progress": 0,
        "createdAt": now,
        "updatedAt": now,
    }
    try:
        result = await db.projects.insert_one(doc)
    except DuplicateKeyError:
        # Two creates for the same name landed between the slug check and here.
        # The code is already unique, so it is what disambiguates the slug.
        doc["slug"] = slug = f"{slug}_{code.lower().replace('-', '_')}"
        result = await db.projects.insert_one(doc)
    doc["_id"] = result.inserted_id

    storage.scaffold(slug)
    await audit.record("project.create", actor, {"projectId": result.inserted_id}, after=code)

    # FR-11: when creating a templated bid, seed from the closest prior quote.
    if mode == "templated":
        priors = await reuse.find_prior(
            brand=doc.get("brand"),
            architect=doc.get("architect"),
            gc=doc.get("gc"),
            exclude_id=result.inserted_id,
            limit=1,
        )
        if priors:
            await reuse.seed_from_prior(doc, priors[0])
            doc = await db.projects.find_one({"_id": result.inserted_id}) or doc

    return await _decorate(doc)


@router.get("/{code}/prior-quotes")
async def prior_quotes(code: str) -> dict[str, Any]:
    """FR-11: closest prior quotes for reuse."""
    project = await load(code)
    rows = await reuse.find_prior(
        brand=project.get("brand"),
        architect=project.get("architect"),
        gc=project.get("gc"),
        exclude_id=project["_id"],
    )
    return {
        "priors": [
            {
                "id": str(row["_id"]),
                "code": row.get("code"),
                "name": row.get("name"),
                "brand": row.get("brand"),
                "architect": row.get("architect"),
                "gc": row.get("gc"),
            }
            for row in rows
        ]
    }


@router.post("/{code}/reuse/{prior_code}")
async def reuse_prior(code: str, prior_code: str, actor: Actor) -> dict[str, Any]:
    project = await load(code)
    prior = await db.projects.find_one({"code": prior_code})
    if not prior:
        raise HTTPException(404, f"prior bid {prior_code!r} not found")
    seeded = await reuse.seed_from_prior(project, prior)
    await audit.record(
        "project.reuse_prior",
        actor,
        {"projectId": project["_id"]},
        after=seeded,
    )
    return serialise({**(await db.projects.find_one({"_id": project["_id"]})), **seeded})


@router.get("/{code}")
async def get_project(code: str) -> dict[str, Any]:
    return await _decorate(await load(code))


@router.patch("/{code}")
async def update_project(code: str, body: ProjectUpdate, actor: Actor) -> dict:
    project = await load(code)
    changes = body.model_dump(exclude_none=True)
    if not changes:
        return await _decorate(project)

    if "bidDue" in changes and changes["bidDue"]:
        changes["bidDue"] = datetime.combine(
            changes["bidDue"], datetime.min.time(), tzinfo=timezone.utc
        )
    if "bidAlternates" in changes:
        changes["bidAlternates"] = [
            str(a).strip() for a in (changes["bidAlternates"] or []) if str(a).strip()
        ]
    if "stage" in changes:
        changes["progress"] = STAGE_PROGRESS.get(changes["stage"], project.get("progress", 0))
    changes["updatedAt"] = datetime.now(timezone.utc)

    await db.projects.update_one({"_id": project["_id"]}, {"$set": changes})
    await audit.record(
        "project.update",
        actor,
        {"projectId": project["_id"]},
        before={k: project.get(k) for k in changes},
        after=changes,
    )
    return await _decorate(await db.projects.find_one({"_id": project["_id"]}))


@router.delete("/{code}", status_code=204, response_class=Response)
async def delete_project(code: str, actor: AdminActor) -> Response:
    """Remove the bid record and all files under projects/{slug}/.

    Admin-only. Cancels outstanding jobs, purges Mongo child collections and
    job history, then deletes the project directory from disk.
    """
    project = await load(code)
    project_id = project["_id"]
    slug = project.get("slug") or ""

    await db.jobs.update_many(
        {"projectId": project_id, "status": {"$in": ["queued", "running"]}},
        {
            "$set": {
                "status": "cancelled",
                "cancelledAt": datetime.now(timezone.utc),
                "cancelledBy": actor,
                "note": "project deleted",
            }
        },
    )
    for collection in (
        db.line_items,
        db.quote_lines,
        db.quotes,
        db.proposals,
        db.documents,
        db.versions,
        db.calls,
    ):
        await collection.delete_many({"projectId": project_id})
    await db.jobs.delete_many({"projectId": project_id})
    await db.projects.delete_one({"_id": project_id})

    try:
        if slug:
            await asyncio.to_thread(storage.purge_project, slug)
    except OSError as exc:
        raise HTTPException(
            500,
            detail=(
                f"{project.get('code')} was removed from the board but its files "
                f"could not be deleted from disk: {exc}. Ask an operator to remove "
                f"projects/{slug}/ manually."
            ),
        ) from exc

    await audit.record(
        "project.delete",
        actor,
        {"projectId": project_id},
        before=project.get("code"),
        note="database and project files purged",
    )
    return Response(status_code=204)
