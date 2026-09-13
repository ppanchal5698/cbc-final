"""The MongoDB client, and the primitives every module's persistence shares.

One Motor client for the process, created lazily so a test can point
`settings.mongodb_uri` somewhere else first, and reset by setting `_client` to
None. Collection accessors do not live here: a module names its own.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from cbc.shared.config import settings

_client: AsyncIOMotorClient | None = None


def client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(
            settings.mongodb_uri,
            tz_aware=True,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=30000,
            maxPoolSize=50,
        )
    return _client


def database() -> AsyncIOMotorDatabase:
    return client()[settings.mongodb_db]


def oid(value: str | ObjectId) -> ObjectId:
    """Coerce to ObjectId, raising a ValueError the routers turn into a 400."""
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(value)
    except (InvalidId, TypeError) as exc:
        raise ValueError(f"not a valid id: {value!r}") from exc


def transactions_enabled() -> bool:
    """Compose sets MONGODB_TRANSACTIONS=1 with the single-node replica set."""
    return os.environ.get("MONGODB_TRANSACTIONS", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


async def run_transaction(callback):
    """Run `await callback(session)` inside a Mongo transaction when enabled.

    When transactions are off (pytest / standalone), calls `callback(None)` so
    writers use ordinary single-document semantics.
    """
    if not transactions_enabled():
        return await callback(None)
    async with await client().start_session() as session:
        async with session.start_transaction():
            return await callback(session)


def serialise(document: Any) -> Any:
    """Recursively turn ObjectId and datetime into JSON-safe values."""
    if isinstance(document, list):
        return [serialise(item) for item in document]
    if isinstance(document, dict):
        return {
            ("id" if key == "_id" else key): serialise(value) for key, value in document.items()
        }
    if isinstance(document, ObjectId):
        return str(document)
    if isinstance(document, datetime):
        return document.isoformat()
    return document
