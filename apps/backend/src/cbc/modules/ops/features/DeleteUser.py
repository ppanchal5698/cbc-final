"""DELETE /api/users/{user_id} - remove someone's sign-in. Admin only.

Returns 200 with a body, unlike most deletes here, which return 204. Pinned by the
characterization suite and flagged, not changed.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from cbc.modules.ops.api import audit
from cbc.modules.ops.infrastructure.collections import users
from cbc.shared.auth import Actor, require_admin
from cbc.shared.mongo import oid

router = APIRouter(prefix="/api/users", tags=["users"], dependencies=[Depends(require_admin)])


@router.delete("/{user_id}")
async def delete_user(user_id: str, actor: Actor) -> dict:
    user = await users().find_one({"_id": oid(user_id)})
    if not user:
        raise HTTPException(404, "user not found")
    if user["email"].lower() == actor.lower():
        raise HTTPException(400, "you cannot delete your own account")

    await users().delete_one({"_id": user["_id"]})
    await audit.record("user.delete", actor, {"userId": user["_id"]}, before=user.get("email"))
    return {"deleted": True, "email": user["email"]}
