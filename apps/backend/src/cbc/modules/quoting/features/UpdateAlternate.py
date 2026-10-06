"""PATCH /api/projects/{code}/alternates/{name} - an alternate's kind, priority or description (FR-14).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from cbc.modules.extraction.api import openings as extraction_openings
from cbc.modules.ops.api import audit
from cbc.modules.projects.api import bids
from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.api import quote as quote_service
from cbc.modules.quoting.domain import alternates
from cbc.modules.quoting.infrastructure.collections import estimate_lines
from cbc.shared.auth import Actor

router = APIRouter(prefix="/api/projects/{code}", tags=["alternates"])


@router.patch("/alternates/{name}")
async def update_alternate(code: str, name: str, body: alternates.AlternateUpdate, actor: Actor) -> dict:
    project = await load(code)
    known = {*(project.get("alternates") or []), *(project.get("bidAlternates") or []),
             *await extraction_openings.distinct_groups(project["_id"]),
             *await estimate_lines().distinct("alternateGroup", {"projectId": project["_id"]})}
    if name not in known or name == alternates.BY_OTHERS_ALTERNATE:
        raise HTTPException(404, f"{name!r} is not an alternate on this bid")

    [current] = alternates.specs(project.get("alternateSpecs"), [name], project.get("bidAlternates"))
    changes = body.model_dump(exclude_unset=True)
    spec = {**current, **{key: value for key, value in changes.items()}}
    await bids.describe_alternate(project["_id"], spec)
    await audit.record("alternate.describe", actor, {"projectId": project["_id"]}, before=current, after=spec)
    # A deductive alternate's lines are in the base bid: its kind moves the total.
    await quote_service.persist(await load(code))
    return spec
