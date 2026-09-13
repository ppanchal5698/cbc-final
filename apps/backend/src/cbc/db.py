"""MongoDB access for the CBC Ops-Hub API.

Collection accessors, index builds and the catalog's read-only user. The client
itself and the primitives (`oid`, `serialise`, transactions) are in
`cbc.shared.mongo`. Accessors are plain attributes so callers read as prose:
`db.quote_lines.find({...})`.
"""
from __future__ import annotations

import os

from urllib.parse import quote_plus, urlsplit

from pymongo import ASCENDING, DESCENDING
from pymongo.errors import OperationFailure, PyMongoError

from cbc.shared.config import settings
from cbc.shared.mongo import client, database
from cbc.persistence import names


class Collections:
    """Named handles, resolved lazily so tests can point at another database.

    The names come from `cbc.persistence.names`, which is where the
    specification's vocabulary lives. Property names stay as the code has always
    spelled them - `db.projects`, `db.quote_lines` - so this change is a rename of
    the stored collections, not of 160 call sites; those move behind repositories
    in their own step.
    """

    @property
    def projects(self):
        return database()[names.BID_REQUESTS]

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
    def jobs(self):
        return database()[names.JOBS]

    @property
    def settings(self):
        """Installation settings - one document per concern, `_id` is the name."""
        return database()[names.SETTINGS]

    @property
    def run_metrics(self):
        """Per-Claude-run cost and provenance, parsed from `.runs/*.log`."""
        return database()[names.RUN_METRICS]

    @property
    def vendor_rfqs(self):
        """FR-16 - the third cost path (§3.28)."""
        return database()[names.VENDOR_RFQS]

    @property
    def rfis(self):
        """Phase 5 questions raised before finalizing (§3.29)."""
        return database()[names.RFIS]

    @property
    def reference_data(self):
        """Curated reference-library documents (margins, tax, tiers, …)."""
        return database()[names.REFERENCE_DATA]


db = Collections()


async def ensure_indexes() -> None:
    """Migrate, then build indexes. Both idempotent, both run at every startup.

    Order matters and is why the two are coupled rather than called separately by
    each of the six services: an index built on `lineItems` before migration 1
    renames it to `openings` would be built on the wrong collection, and building
    it after costs nothing because `renameCollection` carries indexes across.
    """
    from cbc.persistence import migrations

    await migrations.run(database())

    await db.quote_lines.create_index([("projectId", ASCENDING), ("division", ASCENDING)])
    await db.quotes.create_index([("projectId", ASCENDING)], unique=True)
    await db.proposals.create_index([("projectId", ASCENDING)])
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
