"""GET /api/auth/me/{email} - the stored profile for a signed-in address."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from cbc.modules.ops.infrastructure.collections import users
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me/{email}")
async def me(email: str) -> dict:
    user = await users().find_one({"email": email.lower()}, {"passwordHash": 0})
    if not user:
        raise HTTPException(404, "user not found")
    return serialise(user)
