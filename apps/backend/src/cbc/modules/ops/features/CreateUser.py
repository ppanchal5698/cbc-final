"""POST /api/users - register someone who can sign in. Admin only."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from cbc.modules.ops.api import audit
from cbc.modules.ops.domain.passwords import hash_password
from cbc.modules.ops.infrastructure.collections import users
from cbc.shared.auth import Actor, require_admin
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/users", tags=["users"], dependencies=[Depends(require_admin)])


class UserCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    initials: str = Field(min_length=1, max_length=4)
    role: str = Field(default="estimator", pattern="^(admin|estimator)$")
    password: str = Field(min_length=6, max_length=128)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.post("", status_code=201)
async def create_user(body: UserCreate, actor: Actor) -> dict:
    email = body.email.lower()
    if await users().find_one({"email": email}):
        raise HTTPException(409, f"{email} is already registered")

    document = {
        "email": email,
        "name": body.name.strip(),
        "initials": body.initials.strip().upper(),
        "role": body.role,
        "passwordHash": await asyncio.to_thread(hash_password, body.password),
        "createdAt": _now(),
        "updatedAt": _now(),
    }
    result = await users().insert_one(document)
    document["_id"] = result.inserted_id
    await audit.record("user.create", actor, {"userId": result.inserted_id}, after=email)
    return serialise({k: v for k, v in document.items() if k != "passwordHash"})
