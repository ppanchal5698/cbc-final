"""POST /api/projects/{code}/reuse/{prior_code} - mark a bid as templated from a prior one.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from cbc.modules.ops.api import audit
from cbc.modules.projects.api.lookup import load
from cbc.modules.projects.infrastructure import reuse
from cbc.modules.projects.infrastructure.collections import bid_requests
from cbc.shared.auth import Actor
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.post("/{code}/reuse/{prior_code}")
async def reuse_prior(code: str, prior_code: str, actor: Actor) -> dict[str, Any]:
    project = await load(code)
    prior = await bid_requests().find_one({"code": prior_code})
    if not prior:
        raise HTTPException(404, f"prior bid {prior_code!r} not found")
    seeded = await reuse.seed_from_prior(project, prior)
    await audit.record(
        "project.reuse_prior",
        actor,
        {"projectId": project["_id"]},
        after=seeded,
    )
    return serialise({**(await bid_requests().find_one({"_id": project["_id"]})), **seeded})
