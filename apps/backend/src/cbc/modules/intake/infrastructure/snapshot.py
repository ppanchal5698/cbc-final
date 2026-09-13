"""Freezing a bid's openings and quote lines into a new addendum version.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo.errors import DuplicateKeyError

from cbc.modules.extraction.api import openings as extraction_openings
from cbc.modules.quoting.api import lines as quoting_lines
from cbc.modules.intake.infrastructure.collections import versions
from cbc.modules.ops.api import audit
from cbc.modules.projects.api import bids
from cbc.persistence import versioning
from cbc.shared.mongo import serialise


# A snapshot embeds whole documents, against MongoDB's 16 MB per-document limit.
# Silently keeping the first 5 000 would report a complete freeze of an incomplete
# bid - the one thing a version is for is being able to trust it later.
SNAPSHOT_LIMIT = 5000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _within_limit(found: list[dict[str, Any]], label: str) -> list[dict[str, Any]]:
    if len(found) > SNAPSHOT_LIMIT:
        raise ValueError(
            f"this bid has more than {SNAPSHOT_LIMIT} {label}, which is more than a "
            "version snapshot can hold. Snapshotting it would silently freeze an "
            "incomplete record."
        )
    return found


async def snapshot(project: dict[str, Any], reason: str, actor: str) -> dict[str, Any]:
    """Freeze the current line items and quote lines into a new version."""
    project_id = project["_id"]
    line_items = _within_limit(
        await extraction_openings.list_for_project(project_id, limit=SNAPSHOT_LIMIT + 1), "line items"
    )
    quote_lines = _within_limit(
        await quoting_lines.list_for_project(project_id, limit=SNAPSHOT_LIMIT + 1), "quote lines"
    )

    previous = await versions().find_one(
        {"projectId": project_id, "supersededByVersionId": None},
        sort=[("version", -1)],
    )
    document = {
        "projectId": project_id,
        "reason": reason,
        "createdAt": _now(),
        "createdBy": actor,
        "reconciled": False,
        # §3.26: a version is a link in a chain, not a loose document. The head
        # is the one nothing supersedes, which is what the specification indexes
        # for - rather than sorting by number and hoping.
        "previousVersionId": (previous or {}).get("_id"),
        "supersededByVersionId": None,
        "lockedAt": None,
        "status": "draft",
        "statusHistory": [],
        "approvedBy": None,
        "approvedAt": None,
        "lineItemCount": len(line_items),
        "quoteLineCount": len(quote_lines),
        "snapshot": {
            "lineItems": serialise(line_items),
            "quoteLines": serialise(quote_lines),
        },
    }

    # Read-then-write on the version number: two addenda uploaded together both
    # became version n+1, and the addendum diff then attached to whichever one
    # Mongo happened to return. `(projectId, version)` is unique now, so the loser
    # of the race is told to try again rather than quietly sharing a number.
    for _ in range(5):
        latest = await versions().find_one({"projectId": project_id}, sort=[("version", -1)])
        number = (latest or {}).get("version", 0) + 1
        document["version"] = number
        try:
            result = await versions().insert_one(document)
        except DuplicateKeyError:
            document.pop("_id", None)
            continue
        document["_id"] = result.inserted_id
        break
    else:
        raise ValueError("could not allocate a version number; try again")

    # Live lines belong to this version (spec: estimateLines.estimateVersionId).
    # Embedded snapshot stays as the immutable freeze for diffs until S3 fully
    # migrates readers off the blob.
    await quoting_lines.set_version(project_id, document["_id"])
    await extraction_openings.set_version(project_id, document["_id"])

    if previous is not None:
        # Sealing happens after the new version exists, so a crash between the two
        # leaves an unsealed predecessor rather than a chain pointing at nothing.
        await versions().update_one(
            {"_id": previous["_id"]},
            {"$set": versioning.supersede(previous, by_id=result.inserted_id, actor=actor)},
        )

    await bids.set_version(project_id, number)
    await audit.record(
        "version.snapshot",
        actor,
        {"projectId": project_id, "versionId": result.inserted_id},
        after={"version": number, "reason": reason},
    )
    return document
