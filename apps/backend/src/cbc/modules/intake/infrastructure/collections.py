"""The collections intake owns, and the indexes it builds on them.

No other module may name these. Everything else reaches this data through
`cbc.modules.intake.api`.
"""
from __future__ import annotations

from typing import Any

from pymongo import ASCENDING, DESCENDING

from cbc.shared.persistence import names
from cbc.shared.mongo import database, replace_index


def documents():
    return database()[names.DOCUMENTS]


def versions():
    return database()[names.ESTIMATE_VERSIONS]


async def ensure_indexes() -> None:
    """Idempotent. Runs after the migrations, like every module's."""
    await documents().create_index([("projectId", ASCENDING)])
    await replace_index(
        documents(),
        "project_content_sha",
        [("projectId", ASCENDING), ("contentSha", ASCENDING)],
        unique=True,
        partialFilterExpression={
            "contentSha": {"$exists": True, "$type": "string"},
        },
    )
    await replace_index(
        versions(),
        "project_version",
        [("projectId", ASCENDING), ("version", DESCENDING)],
        unique=True,
    )


async def delete_for_project(project_id: Any) -> None:
    """A bid is being deleted: its documents and versions go with it. Files stay on disk."""
    await documents().delete_many({"projectId": project_id})
    await versions().delete_many({"projectId": project_id})
