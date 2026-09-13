"""GET /api/users - everyone who can sign in. Admin only."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from cbc.modules.ops.infrastructure.collections import users
from cbc.shared.auth import require_admin
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/users", tags=["users"], dependencies=[Depends(require_admin)])


@router.get("")
async def list_users() -> dict:
    found = await users().find({}, {"passwordHash": 0}).sort("email", 1).to_list(200)
    return {"users": serialise(found)}
