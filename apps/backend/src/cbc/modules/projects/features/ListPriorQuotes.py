"""GET /api/projects/{code}/prior-quotes - the closest prior bids to reuse (FR-11).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from cbc.modules.projects.api.lookup import load
from cbc.modules.projects.infrastructure import reuse

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("/{code}/prior-quotes")
async def prior_quotes(code: str) -> dict[str, Any]:
    """FR-11: closest prior quotes for reuse."""
    project = await load(code)
    rows = await reuse.find_prior(
        brand=project.get("brand"),
        architect=project.get("architect"),
        gc=project.get("gc"),
        exclude_id=project["_id"],
    )
    return {
        "priors": [
            {
                "id": str(row["_id"]),
                "code": row.get("code"),
                "name": row.get("name"),
                "brand": row.get("brand"),
                "architect": row.get("architect"),
                "gc": row.get("gc"),
            }
            for row in rows
        ]
    }
