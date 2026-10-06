"""POST /api/projects/{code}/alternates - name a new, empty alternate group, with its kind and priority.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from cbc.modules.ops.api import audit
from cbc.modules.projects.api import bids
from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.domain.alternates import PENDING_NOTE, AlternateCreate
from cbc.shared.auth import Actor

router = APIRouter(prefix="/api/projects/{code}", tags=["alternates"])


@router.post("/alternates", status_code=201)
async def create_alternate(code: str, body: AlternateCreate, actor: Actor) -> dict:
    project = await load(code)
    name = body.name.strip()

    if name in (project.get("alternates") or []) or name in (project.get("bidAlternates") or []):
        raise HTTPException(409, f"{name} already exists on this bid")

    spec = {"name": name, "kind": body.kind, "priority": body.priority, "description": body.description}
    await bids.add_alternate(project["_id"], name)
    await bids.describe_alternate(project["_id"], spec)
    await audit.record("alternate.create", actor, {"projectId": project["_id"]}, after=spec)
    return {
        "name": name,
        "label": name,
        "isBase": False,
        "kind": body.kind,
        "priority": body.priority,
        "description": body.description,
        "lineItemCount": 0,
        "quoteLineCount": 0,
        "note": "Empty. Move lines into it, or add them by hand. " + PENDING_NOTE,
    }
