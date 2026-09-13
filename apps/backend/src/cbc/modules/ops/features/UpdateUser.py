"""PATCH /api/users/{user_id} - change a name, initials, role or password. Admin only."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from cbc.modules.ops.api import audit
from cbc.modules.ops.domain.passwords import hash_password
from cbc.modules.ops.infrastructure.collections import users
from cbc.shared.auth import Actor, require_admin
from cbc.shared.mongo import oid, serialise

router = APIRouter(prefix="/api/users", tags=["users"], dependencies=[Depends(require_admin)])


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    initials: str | None = Field(default=None, min_length=1, max_length=4)
    role: str | None = Field(default=None, pattern="^(admin|estimator)$")
    password: str | None = Field(default=None, min_length=6, max_length=128)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.patch("/{user_id}")
async def update_user(user_id: str, body: UserUpdate, actor: Actor) -> dict:
    user = await users().find_one({"_id": oid(user_id)})
    if not user:
        raise HTTPException(404, "user not found")

    changes = body.model_dump(exclude_none=True)
    if not changes:
        return serialise({k: v for k, v in user.items() if k != "passwordHash"})

    if "password" in changes:
        changes["passwordHash"] = await asyncio.to_thread(
            hash_password, changes.pop("password")
        )
    if "initials" in changes:
        changes["initials"] = changes["initials"].strip().upper()
    changes["updatedAt"] = _now()

    await users().update_one({"_id": user["_id"]}, {"$set": changes})
    await audit.record(
        "user.update",
        actor,
        {"userId": user["_id"]},
        before={k: user.get(k) for k in changes if k != "passwordHash"},
        after={k: v for k, v in changes.items() if k != "passwordHash"},
    )
    updated = await users().find_one({"_id": user["_id"]}, {"passwordHash": 0})
    return serialise(updated)
