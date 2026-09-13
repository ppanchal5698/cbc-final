"""The MongoDB client, and the primitives every module's persistence shares.

One Motor client for the process, created lazily so a test can point
`settings.mongodb_uri` somewhere else first, and reset by setting `_client` to
None. Collection accessors do not live here: a module names its own.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import OperationFailure

from cbc.shared.config import settings

log = logging.getLogger("cbc.api.db")  # the name these index messages have always logged under

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


# ── index builds that survive a peer racing them ─────────────────────────────


# Mongo aborts an in-flight build when another client drops the same index
# name (common when every API runs ensure_indexes on compose up).
INDEX_BUILD_ABORTED = 276


async def create_index_resilient(collection, keys, **options) -> None:
    """create_index with a short retry when a peer aborts the build."""
    delay = 0.2
    for attempt in range(5):
        try:
            await collection.create_index(keys, **options)
            return
        except OperationFailure as exc:
            # Peer dropped this index mid-build.
            if exc.code == INDEX_BUILD_ABORTED and attempt < 4:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 2.0)
                continue
            # Same key under another name (e.g. auto-named part_1 vs part_lookup).
            if exc.code == 85 and "different name" in (exc.details or {}).get("errmsg", exc.errmsg or ""):
                other = None
                msg = (exc.details or {}).get("errmsg") or exc.errmsg or ""
                # "... different name: part_1"
                if "different name:" in msg:
                    other = msg.rsplit("different name:", 1)[-1].strip().rstrip(".")
                if other and options.get("name") and other != options["name"]:
                    try:
                        await collection.drop_index(other)
                        log.info(
                            "dropped %s.%s (same key as %s)",
                            collection.name,
                            other,
                            options["name"],
                        )
                    except OperationFailure:
                        pass
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 2.0)
                    continue
            raise


async def replace_index(collection, name: str, keys, **options) -> None:
    """Create an index, replacing an existing one whose options differ.

    `create_index` is idempotent only while the options match; changing them on an
    index that already exists raises rather than migrating, which would leave a
    tightened constraint silently un-applied on every database that already had
    the old one - that is, all of them.
    """
    try:
        await create_index_resilient(collection, keys, name=name, **options)
        return
    except OperationFailure as exc:
        if exc.code not in (85, 86):  # IndexOptionsConflict, IndexKeySpecsConflict
            raise
    try:
        await collection.drop_index(name)
    except OperationFailure:
        pass
    await create_index_resilient(collection, keys, name=name, **options)
