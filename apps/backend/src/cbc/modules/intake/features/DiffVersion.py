"""GET /api/projects/{code}/versions/{version}/diff - what changed since a version was frozen.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from cbc.modules.intake.domain.versions import PENDING_NOTE
from cbc.modules.intake.infrastructure import reconcile
from cbc.modules.intake.infrastructure.collections import versions
from cbc.modules.projects.api.lookup import load
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/projects/{code}", tags=["versions"])


@router.get("/versions/{version}/diff")
async def diff_version(code: str, version: int) -> dict[str, Any]:
    project = await load(code)
    stored = await versions().find_one({"projectId": project["_id"], "version": version})
    if not stored:
        raise HTTPException(404, f"version {version} not found")

    found = await reconcile.rows(project, stored)
    doors = [row for row in found if row["kind"] == "opening"]
    return {
        "version": version,
        # The doors, as this read always gave them.
        "added": [row["key"] for row in doors if row["change"] == "added"],
        "removed": [row["key"] for row in doors if row["change"] == "removed"],
        "changed": [
            {"mark": row["key"], "fields": row["fields"], "before": row["before"], "after": row["after"]}
            for row in doors if row["change"] == "changed"
        ],
        # Every difference, doors and quote lines, each for the estimator to keep or revert.
        "rows": serialise(found),
        "undecided": len(reconcile.undecided(found)),
        "pending": PENDING_NOTE,
    }
