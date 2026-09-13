"""MongoDB access for the CBC Ops-Hub API.

Collection accessors, index builds and the catalog's read-only user. The client
itself and the primitives (`oid`, `serialise`, transactions) are in
`cbc.shared.mongo`. Accessors are plain attributes so callers read as prose:
`db.line_items.find({...})`.
"""
from __future__ import annotations

import asyncio
import logging
import os

from urllib.parse import quote_plus, urlsplit

from pymongo import ASCENDING, DESCENDING, TEXT
from pymongo.errors import DuplicateKeyError, OperationFailure, PyMongoError

from cbc.shared.config import settings
from cbc.shared.mongo import INDEX_BUILD_ABORTED, client, create_index_resilient, database, replace_index
from cbc.persistence import names

log = logging.getLogger("cbc.api.db")

class Collections:
    """Named handles, resolved lazily so tests can point at another database.

    The names come from `cbc.persistence.names`, which is where the
    specification's vocabulary lives. Property names stay as the code has always
    spelled them - `db.projects`, `db.line_items` - so this change is a rename of
    the stored collections, not of 160 call sites; those move behind repositories
    in their own step.
    """

    @property
    def projects(self):
        return database()[names.BID_REQUESTS]

    @property
    def documents(self):
        return database()[names.DOCUMENTS]

    @property
    def line_items(self):
        return database()[names.OPENINGS]

    @property
    def quote_lines(self):
        return database()[names.ESTIMATE_LINES]

    @property
    def quotes(self):
        return database()[names.QUOTES]

    @property
    def proposals(self):
        return database()[names.PROPOSALS]

    @property
    def products(self):
        return database()[names.CATALOG_ITEMS]

    @property
    def price_books(self):
        return database()[names.PRICE_BOOKS]

    @property
    def jobs(self):
        return database()[names.JOBS]

    @property
    def versions(self):
        return database()[names.ESTIMATE_VERSIONS]

    @property
    def settings(self):
        """Installation settings - one document per concern, `_id` is the name."""
        return database()[names.SETTINGS]

    @property
    def run_metrics(self):
        """Per-Claude-run cost and provenance, parsed from `.runs/*.log`."""
        return database()[names.RUN_METRICS]

    @property
    def failed_extractions(self):
        """Claude payloads that failed the schema gate, kept for operators."""
        return database()[names.FAILED_EXTRACTIONS]

    @property
    def feedback_events(self):
        """FR-13 - every estimator correction, structured (§3.31)."""
        return database()[names.FEEDBACK_EVENTS]

    @property
    def vendor_rfqs(self):
        """FR-16 - the third cost path (§3.28)."""
        return database()[names.VENDOR_RFQS]

    @property
    def rfis(self):
        """Phase 5 questions raised before finalizing (§3.29)."""
        return database()[names.RFIS]

    @property
    def takeoffs(self):
        """FR-12 - FRP geometry (§3.24)."""
        return database()[names.TAKEOFFS]

    @property
    def reference_data(self):
        """Curated reference-library documents (margins, tax, tiers, …)."""
        return database()[names.REFERENCE_DATA]


db = Collections()


async def _ensure_part_lookup_index() -> None:
    """Ensure non-unique `part_lookup`; migrate away from auto-named `part_1`.

    Older startups created `[("part", ASCENDING)]` without a name, so Mongo
    called it `part_1` (same as the legacy unique index). Creating `part_lookup`
    on the same key then fails with IndexOptionsConflict. Drop any leftover
    `part_1` — unique or not — then create the named lookup index.
    """
    try:
        info = await db.products.index_information()
    except OperationFailure:
        info = {}
    if "part_lookup" in info:
        return
    if "part_1" in info:
        try:
            await db.products.drop_index("part_1")
            log.info("dropped products.part_1 (migrating to part_lookup)")
        except OperationFailure as exc:
            if exc.code != INDEX_BUILD_ABORTED:
                log.debug("products.part_1 drop skipped: %s", exc)
            await asyncio.sleep(0.3)
    await create_index_resilient(
        db.products, [("part", ASCENDING)], name="part_lookup"
    )


async def ensure_indexes() -> None:
    """Migrate, then build indexes. Both idempotent, both run at every startup.

    Order matters and is why the two are coupled rather than called separately by
    each of the six services: an index built on `lineItems` before migration 1
    renames it to `openings` would be built on the wrong collection, and building
    it after costs nothing because `renameCollection` carries indexes across.
    """
    from cbc.persistence import migrations

    await migrations.run(database())

    await db.documents.create_index([("projectId", ASCENDING)])
    await replace_index(
        db.documents,
        "project_content_sha",
        [("projectId", ASCENDING), ("contentSha", ASCENDING)],
        unique=True,
        partialFilterExpression={
            "contentSha": {"$exists": True, "$type": "string"},
        },
    )
    await db.line_items.create_index([("projectId", ASCENDING), ("status", ASCENDING)])
    await replace_index(
        db.line_items,
        "opening_door_identity",
        [("orgId", ASCENDING), ("projectId", ASCENDING), ("doorNumber", ASCENDING)],
        unique=True,
        partialFilterExpression={
            "doorNumber": {"$exists": True, "$type": "string"},
        },
    )
    # Legacy non-unique mark lookup kept for list screens that still sort by mark.
    await db.line_items.create_index([("projectId", ASCENDING), ("mark", ASCENDING)])
    await db.quote_lines.create_index([("projectId", ASCENDING), ("division", ASCENDING)])
    await db.quotes.create_index([("projectId", ASCENDING)], unique=True)
    await db.proposals.create_index([("projectId", ASCENDING)])
    # Hager's 1234 and Rockwood's 1234 are different parts. A unique index on
    # `part` alone made the price-book ingest upsert one over the other, so the
    # second vendor's sheet silently replaced the first vendor's costs.
    #
    # The legacy unique index was auto-named `part_1`. An unnamed non-unique
    # `[("part", ASCENDING)]` gets the same name — concurrent drop/create races
    # abort index builds, and a leftover non-unique `part_1` blocks creating
    # `part_lookup`. Migrate explicitly via `_ensure_part_lookup_index`.
    await _ensure_part_lookup_index()
    await create_index_resilient(db.products, [("division", ASCENDING)])
    try:
        await replace_index(
            db.products,
            "product_identity",
            [("manufacturer", ASCENDING), ("part", ASCENDING)],
            unique=True,
        )
    except DuplicateKeyError:
        log.error(
            "products already holds two rows with the same manufacturer and part, so "
            "the unique index could not be built. Run scripts/dedupe_products.py, "
            "then restart. Ingest is keyed on (manufacturer, part) either way."
        )
    await db.products.create_index(
        [("part", TEXT), ("description", TEXT), ("manufacturer", TEXT)],
        name="product_search",
    )
    await db.price_books.create_index([("vendor", ASCENDING), ("program", ASCENDING)])
    await db.failed_extractions.create_index(
        [("projectId", ASCENDING), ("createdAt", DESCENDING)]
    )
    await db.failed_extractions.create_index([("jobId", ASCENDING)])
    await replace_index(
        db.versions,
        "project_version",
        [("projectId", ASCENDING), ("version", DESCENDING)],
        unique=True,
    )
    # Alternates are queried per group on both the extraction and quote screens.
    await db.line_items.create_index([("projectId", ASCENDING), ("alternateGroup", ASCENDING)])
    await db.quote_lines.create_index([("projectId", ASCENDING), ("alternateGroup", ASCENDING)])
    await db.reference_data.create_index([("family", ASCENDING)], unique=True)
    await db.reference_data.create_index([("updatedAt", DESCENDING)])
    from cbc.services.reference_store import ensure_reference_seed

    await ensure_reference_seed()


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
        return explicit

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
    return (
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
