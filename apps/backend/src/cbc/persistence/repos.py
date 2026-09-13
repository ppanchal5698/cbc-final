"""Resolve a Repository for the common API call pattern.

Projects carry `orgId` from the envelope backfill. Callers pass the loaded
project (or an explicit org id) and the actor; every write then injects both.
"""
from __future__ import annotations

from typing import Any

from cbc.shared.mongo import database
from cbc.persistence import envelope, names
from cbc.persistence.repository import Repository

# Stable CBC org slug from migration m002; used when a legacy project lacks orgId.
CBC_ORG_SLUG = "cbc"

# Matrix 2.0 identity - same payload m002 upserts, so a test DB that was dropped
# mid-session can still resolve a tenant without waiting for a restart.
_CBC = {
    "slug": "cbc",
    "name": "Construction Building Components",
    "parent": "The Hamilton Parker Company",
    "description": "Hamilton Parker's national-accounts division",
    "address": {
        "street": "1865 Leonard Ave",
        "city": "Columbus",
        "state": "OH",
        "country": "US",
    },
}


async def org_id_for(project: dict[str, Any] | None = None) -> Any:
    if project and project.get("orgId") is not None:
        return project["orgId"]
    orgs = database()[names.ORGANIZATIONS]
    org = await orgs.find_one({"slug": CBC_ORG_SLUG}, {"_id": 1})
    if org:
        return org["_id"]
    # Idempotent mint - mirrors m002 so API writes never fail on a fresh DB.
    await orgs.update_one(
        {"slug": CBC_ORG_SLUG},
        {
            "$set": {**_CBC, "updatedAt": envelope.now()},
            "$setOnInsert": {
                "schemaVersion": envelope.SCHEMA_VERSION,
                "createdAt": envelope.now(),
                "createdBy": None,
                "updatedBy": None,
            },
        },
        upsert=True,
    )
    org = await orgs.find_one({"slug": CBC_ORG_SLUG}, {"_id": 1})
    if not org:
        raise RuntimeError("CBC organization missing - run migrations")
    return org["_id"]


def repo(collection, *, org_id: Any, actor_id: Any = None) -> Repository:
    return Repository(collection, org_id=org_id, actor_id=actor_id)


async def for_project(collection, project: dict[str, Any], actor_id: Any = None) -> Repository:
    return Repository(collection, org_id=await org_id_for(project), actor_id=actor_id)
