"""POST /api/auth/verify - are these credentials good, and who is it?

NextAuth owns the session; this endpoint only answers the question. Passwords are
bcrypt-hashed and never leave the database.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr

from cbc.modules.ops.domain.passwords import verify_password
from cbc.modules.ops.infrastructure.collections import AUTH_ATTEMPT_TTL, auth_attempts, users

router = APIRouter(prefix="/api/auth", tags=["auth"])

# `/api/auth/verify` is the one endpoint reachable without the internal token -
# NextAuth calls it - so it is the one endpoint a stranger can hammer.
#
# The count lives in Mongo, one document per attempt, expired by a TTL index.
# It used to be an in-process dict, which meant the budget was per API process:
# two replicas behind a load balancer gave an attacker twice the attempts, and a
# restart gave them a fresh ten. The window is enforced by the `at` filter below
# rather than by the TTL sweep, so it is exact regardless of when Mongo last
# collected.
MAX_ATTEMPTS = 10
WINDOW_SECONDS = AUTH_ATTEMPT_TTL

# Verifying a password that does not exist has to cost the same as one that does.
# Skipping bcrypt on a miss returned in microseconds where a hit took ~100 ms,
# which told an attacker which addresses are registered - the thing the identical
# error message below is trying not to say.
_DUMMY_HASH = bcrypt.hashpw(b"never-matches", bcrypt.gensalt()).decode("utf-8")


class Credentials(BaseModel):
    email: EmailStr
    password: str


async def _too_many(email: str) -> bool:
    """Record this attempt and say whether the window is now over budget."""
    now = datetime.now(timezone.utc)
    await auth_attempts().insert_one({"email": email, "at": now})
    recent = await auth_attempts().count_documents(
        {"email": email, "at": {"$gte": now - timedelta(seconds=WINDOW_SECONDS)}}
    )
    return recent > MAX_ATTEMPTS


@router.post("/verify")
async def verify(body: Credentials) -> dict:
    email = body.email.lower()
    if await _too_many(email):
        raise HTTPException(429, "too many sign-in attempts; wait a few minutes")

    user = await users().find_one({"email": email})
    # Same response either way, and the same amount of work either way - do not
    # reveal whether an address is registered, by wording or by timing.
    hashed = user.get("passwordHash", "") if user else _DUMMY_HASH
    correct = await asyncio.to_thread(verify_password, body.password, hashed)
    if not user or not correct:
        raise HTTPException(401, "invalid email or password")

    # A correct password clears the budget, so a person who mistypes four times
    # and then gets it right is not locked out by their own success.
    await auth_attempts().delete_many({"email": email})

    await users().update_one(
        {"_id": user["_id"]}, {"$set": {"lastSeenAt": datetime.now(timezone.utc)}}
    )
    return {
        "id": str(user["_id"]),
        "email": user["email"],
        "name": user.get("name", user["email"]),
        "initials": user.get("initials", user["email"][:2].upper()),
        "role": user.get("role", "estimator"),
    }
