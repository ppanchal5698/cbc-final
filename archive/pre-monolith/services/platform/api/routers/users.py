"""User administration — admin only."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from cbc.db import db, oid, serialise
from cbc.http.deps import Actor, require_admin
from api.routers.auth import hash_password
from cbc.schemas import UserCreate, UserUpdate
from cbc.services import audit

router = APIRouter(
    prefix="/api/users",
    tags=["users"],
    dependencies=[Depends(require_admin)],
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _public(user: dict) -> dict:
    return serialise({k: v for k, v in user.items() if k != "passwordHash"})


@router.get("")
async def list_users() -> dict:
    found = await db.users.find({}, {"passwordHash": 0}).sort("email", 1).to_list(200)
    return {"users": serialise(found)}


@router.post("", status_code=201)
async def create_user(body: UserCreate, actor: Actor) -> dict:
    email = body.email.lower()
    if await db.users.find_one({"email": email}):
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
    result = await db.users.insert_one(document)
    document["_id"] = result.inserted_id
    await audit.record("user.create", actor, {"userId": result.inserted_id}, after=email)
    return _public(document)


@router.patch("/{user_id}")
async def update_user(user_id: str, body: UserUpdate, actor: Actor) -> dict:
    user = await db.users.find_one({"_id": oid(user_id)})
    if not user:
        raise HTTPException(404, "user not found")

    changes = body.model_dump(exclude_none=True)
    if not changes:
        return _public(user)

    if "password" in changes:
        changes["passwordHash"] = await asyncio.to_thread(
            hash_password, changes.pop("password")
        )
    if "initials" in changes:
        changes["initials"] = changes["initials"].strip().upper()
    changes["updatedAt"] = _now()

    await db.users.update_one({"_id": user["_id"]}, {"$set": changes})
    await audit.record(
        "user.update",
        actor,
        {"userId": user["_id"]},
        before={k: user.get(k) for k in changes if k != "passwordHash"},
        after={k: v for k, v in changes.items() if k != "passwordHash"},
    )
    updated = await db.users.find_one({"_id": user["_id"]}, {"passwordHash": 0})
    return serialise(updated)


@router.delete("/{user_id}")
async def delete_user(user_id: str, actor: Actor) -> dict:
    user = await db.users.find_one({"_id": oid(user_id)})
    if not user:
        raise HTTPException(404, "user not found")
    if user["email"].lower() == actor.lower():
        raise HTTPException(400, "you cannot delete your own account")

    await db.users.delete_one({"_id": user["_id"]})
    await audit.record("user.delete", actor, {"userId": user["_id"]}, before=user.get("email"))
    return {"deleted": True, "email": user["email"]}
