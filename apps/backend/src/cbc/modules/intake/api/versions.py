"""Addendum versions, for the pass that diffs an addendum against them."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from cbc.modules.intake.infrastructure.collections import versions


async def record_addendum_diff(project_id: Any, version: int, diff: dict[str, Any]) -> bool:
    """Attach an addendum diff to its version and mark it unreconciled. False if there is no such version."""
    result = await versions().update_one(
        {"projectId": project_id, "version": version},
        {"$set": {"addendumDiff": diff, "reconciled": False, "diffImportedAt": datetime.now(timezone.utc)}},
    )
    return bool(result.matched_count)
