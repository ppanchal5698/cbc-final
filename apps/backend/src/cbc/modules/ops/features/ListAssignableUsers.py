"""GET /api/users/directory - who a bid may be assigned to.

Readable by any signed-in actor, unlike the admin-only `/api/users`: the board
already prints these names beside every bid, and the estimator picker needs the
list to offer. It carries no role, no password hash and no account state.
"""
from __future__ import annotations

from fastapi import APIRouter

from cbc.modules.ops.api import identity
from cbc.shared.auth import Actor

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/directory")
async def list_assignable_users(actor: Actor) -> dict:
    return {"users": await identity.assignable()}
