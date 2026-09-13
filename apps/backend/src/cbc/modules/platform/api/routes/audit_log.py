"""Read-only audit log for administrators (NFR-3)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from cbc.db import db
from cbc.shared.mongo import serialise
from cbc.shared.auth import Actor, require_admin

router = APIRouter(prefix="/api/audit", tags=["audit"], dependencies=[Depends(require_admin)])


@router.get("")
async def list_audit(
    actor: Actor,
    action: str | None = None,
    project: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    skip: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if action:
        query["action"] = action
    if project:
        from cbc.http.projects_access import load

        loaded = await load(project)
        query["target.projectId"] = loaded["_id"]

    cursor = db.audit_log.find(query).sort("at", -1).skip(skip).limit(limit)
    entries = await cursor.to_list(limit)
    total = await db.audit_log.count_documents(query)
    return {"entries": serialise(entries), "total": total, "skip": skip, "limit": limit}
