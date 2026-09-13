"""GET /api/audit - the read-only audit log, newest first (NFR-3). Admin only."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from cbc.modules.ops.api import project_lookup
from cbc.modules.ops.infrastructure.collections import audit_logs
from cbc.shared.auth import Actor, require_admin
from cbc.shared.mongo import serialise

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
        query["target.projectId"] = await project_lookup.project_id(project)

    cursor = audit_logs().find(query).sort("at", -1).skip(skip).limit(limit)
    entries = await cursor.to_list(limit)
    total = await audit_logs().count_documents(query)
    return {"entries": serialise(entries), "total": total, "skip": skip, "limit": limit}
