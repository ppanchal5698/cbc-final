"""The MongoDB client, and the primitives every module's persistence shares.

One Motor client for the process, created lazily so a test can point
`settings.mongodb_uri` somewhere else first, and reset by setting `_client` to
None. Collection accessors do not live here: a module names its own. The
read-only connection the catalog MCP server is handed, and the user behind it, do.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any
from urllib.parse import quote_plus, urlsplit

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import OperationFailure, PyMongoError

from cbc.shared.config import settings
from cbc.shared.mongo_uri import reachable_uri

log = logging.getLogger("cbc.api.db")  # the name these index messages have always logged under

_client: AsyncIOMotorClient | None = None


def client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(
            reachable_uri(settings.mongodb_uri),
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
            # OperationFailure has no `errmsg` attribute in pymongo 4; reading it as a
            # .get() default raised AttributeError on every conflict this handles.
            msg = (exc.details or {}).get("errmsg") or str(exc)
            if exc.code == 85 and "different name" in msg:
                other = None
                # "... different name: part_1"
                if "different name:" in msg:
                    other = msg.rsplit("different name:", 1)[-1].strip().rstrip(".")
                # A text index (a collection holds one): "... different name and options.
                # Requested index: {...}, existing index: { ..., name: "sku_text", ... }"
                elif 'name: "' in msg.partition("existing index:")[2]:
                    other = msg.partition("existing index:")[2].split('name: "', 1)[1].split('"', 1)[0]
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


# ── read-only access for the catalog MCP server ─────────────────────────────
#
# `MONGODB_URI` authenticates as root@admin. That is right for the API, which
# owns every collection, and wrong for the one thing Claude Code is allowed to
# reach: the catalog server reads products and price books and asserts at import
# that it exposes no write tools.
#
# That assertion only governs the tools. It says nothing about the credentials
# the server holds, and until this existed the server held the superuser's - so
# "the catalog is read-only" was a convention rather than something the database
# would enforce.

READONLY_USER = "cbc_catalog_ro"


def _readonly_password() -> str:
    return os.environ.get("MONGODB_READONLY_PASSWORD", "cbc_catalog_ro_local_dev")


def readonly_uri() -> str | None:
    """A connection string that cannot write, or None when there isn't one.

    `MONGODB_READONLY_URI` wins: in production the user is provisioned by whoever
    owns the cluster and handed over as a secret, not created by an application
    at startup.
    """
    explicit = os.environ.get("MONGODB_READONLY_URI")
    if explicit:
        return reachable_uri(explicit)

    parsed = urlsplit(settings.mongodb_uri)
    if not parsed.hostname:
        return None

    host = parsed.hostname + (f":{parsed.port}" if parsed.port else "")
    credentials = f"{quote_plus(READONLY_USER)}:{quote_plus(_readonly_password())}"
    # Authenticate against the database the user was actually created in.
    #
    # This used to inherit the parent URI's query string, which carries
    # `authSource=admin` because the root user lives there - while
    # `ensure_readonly_user` creates this one in the application database. The
    # two never matched, and nothing noticed because neither function had ever
    # been called: the first real connection failed authentication.
    return reachable_uri(
        f"{parsed.scheme}://{credentials}@{host}/{settings.mongodb_db}"
        f"?authSource={settings.mongodb_db}"
    )


async def ensure_readonly_user() -> bool:
    """Create or refresh the read-only user. True when one is usable.

    Idempotent, and a no-op when the cluster already provides the credentials.
    Failure is reported rather than raised: a pricing pass falling back to the
    writable URI is worse than ideal, but a pipeline that will not start at all
    because of a privilege refinement is worse still. The caller says which
    happened.
    """
    if os.environ.get("MONGODB_READONLY_URI"):
        return True

    database_name = settings.mongodb_db
    roles = [{"role": "read", "db": database_name}]
    try:
        target = client()[database_name]
        try:
            await target.command(
                "createUser", READONLY_USER, pwd=_readonly_password(), roles=roles
            )
        except OperationFailure as exc:
            if exc.code != 51003:  # already exists
                raise
            # Keep it aligned with the configured password and role on every boot.
            await target.command(
                "updateUser", READONLY_USER, pwd=_readonly_password(), roles=roles
            )
        return True
    except (OperationFailure, PyMongoError):
        return False
