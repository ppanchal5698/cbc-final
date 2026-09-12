"""Credential verification for NextAuth.

NextAuth owns the session; this endpoint only answers "are these credentials
good, and who is it?". Passwords are bcrypt-hashed and never leave the database.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import APIRouter, HTTPException

from cbc.db import AUTH_ATTEMPT_TTL, db, serialise
from cbc.schemas import Credentials

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


async def _too_many(email: str) -> bool:
    """Record this attempt and say whether the window is now over budget."""
    now = datetime.now(timezone.utc)
    await db.auth_attempts.insert_one({"email": email, "at": now})
    recent = await db.auth_attempts.count_documents(
        {"email": email, "at": {"$gte": now - timedelta(seconds=WINDOW_SECONDS)}}
    )
    return recent > MAX_ATTEMPTS


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


@router.post("/verify")
async def verify(body: Credentials) -> dict:
    email = body.email.lower()
    if await _too_many(email):
        raise HTTPException(429, "too many sign-in attempts; wait a few minutes")

    user = await db.users.find_one({"email": email})
    # Same response either way, and the same amount of work either way - do not
    # reveal whether an address is registered, by wording or by timing.
    hashed = user.get("passwordHash", "") if user else _DUMMY_HASH
    correct = await asyncio.to_thread(verify_password, body.password, hashed)
    if not user or not correct:
        raise HTTPException(401, "invalid email or password")

    # A correct password clears the budget, so a person who mistypes four times
    # and then gets it right is not locked out by their own success.
    await db.auth_attempts.delete_many({"email": email})

    await db.users.update_one(
        {"_id": user["_id"]}, {"$set": {"lastSeenAt": datetime.now(timezone.utc)}}
    )
    return {
        "id": str(user["_id"]),
        "email": user["email"],
        "name": user.get("name", user["email"]),
        "initials": user.get("initials", user["email"][:2].upper()),
        "role": user.get("role", "estimator"),
    }


@router.get("/me/{email}")
async def me(email: str) -> dict:
    user = await db.users.find_one({"email": email.lower()}, {"passwordHash": 0})
    if not user:
        raise HTTPException(404, "user not found")
    return serialise(user)
