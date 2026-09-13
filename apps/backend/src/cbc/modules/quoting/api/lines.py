"""A bid's quote lines, for the modules and the gate that read or stamp them."""
from __future__ import annotations

from typing import Any

from cbc.modules.quoting.infrastructure.collections import estimate_lines


async def list_for_project(project_id: Any, *, limit: int | None = None) -> list[dict[str, Any]]:
    return await estimate_lines().find({"projectId": project_id}).to_list(limit)


async def set_version(project_id: Any, version_id: Any) -> None:
    """Live quote lines belong to this version (estimateVersionId), after a snapshot."""
    await estimate_lines().update_many({"projectId": project_id}, {"$set": {"estimateVersionId": version_id}})
