"""POST /api/projects - open a bid: allocate its code, scaffold its files, seed a templated one.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from cbc.modules.ops.api import audit, pipeline as ops_pipeline
from cbc.modules.projects.domain.bid import ProjectCreate
from cbc.modules.projects.infrastructure import reuse
from cbc.modules.projects.infrastructure.board import decorate
from cbc.modules.projects.infrastructure.collections import bid_requests, counters
from cbc.services import storage  # ponytail: legacy kernel; the bid's file tree moves to shared/ in Phase 4
from cbc.shared.auth import Actor

router = APIRouter(prefix="/api/projects", tags=["projects"])


async def next_code() -> str:
    """Allocate the next CBC-YYNNNN atomically."""
    prefix = storage.code_prefix()
    counter = await counters().find_one_and_update(
        {"_id": prefix},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    if counter["seq"] == 1:
        # First allocation under this prefix. The database may already carry codes
        # issued before the counter existed, so continue that series instead of
        # restarting on top of it. Costs one scan per prefix, once.
        highest = storage.highest_code_sequence(await bid_requests().distinct("code"), prefix)
        if highest >= 1:
            counter = await counters().find_one_and_update(
                {"_id": prefix},
                {"$set": {"seq": highest + 1}},
                return_document=ReturnDocument.AFTER,
            )
    return f"{prefix}{counter['seq']:04d}"


@router.post("", status_code=201)
async def create_project(body: ProjectCreate, actor: Actor) -> dict[str, Any]:
    code = await next_code()

    # Unless the bid says otherwise, the installation default decides. False out
    # of the box: the gated flow is what CLAUDE.md describes, and autopilot prices
    # openings nobody has checked.
    autopilot = body.autopilot
    if autopilot is None:
        autopilot = await ops_pipeline.autopilot_default()

    slug = storage.slugify(body.name)
    if await bid_requests().find_one({"slug": slug}):
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
        result = await bid_requests().insert_one(doc)
    except DuplicateKeyError:
        # Two creates for the same name landed between the slug check and here.
        # The code is already unique, so it is what disambiguates the slug.
        doc["slug"] = slug = f"{slug}_{code.lower().replace('-', '_')}"
        result = await bid_requests().insert_one(doc)
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
            doc = await bid_requests().find_one({"_id": result.inserted_id}) or doc

    return await decorate(doc)
