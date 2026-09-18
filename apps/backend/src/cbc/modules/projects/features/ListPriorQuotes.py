"""GET /api/projects/{code}/prior-quotes - the closest prior bids to reuse (FR-11).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from cbc.modules.projects.api.lookup import load
from cbc.modules.projects.api import board_sources
from cbc.modules.projects.infrastructure import reuse

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _line_count(quote: dict[str, Any] | None) -> int | None:
    """How many lines that quote came to. The stored quote counts per group."""
    groups = (quote or {}).get("groups")
    if not isinstance(groups, list):
        return None
    return sum(int(group.get("line_count") or 0) for group in groups if isinstance(group, dict))


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
    # The proposal compares this bid against the closest prior one, so the
    # totals ride along: a list of names answers "which one", not "how did it
    # come out".
    totals = await board_sources.quotes([row["_id"] for row in rows])
    return {
        "priors": [
            {
                "id": str(row["_id"]),
                "code": row.get("code"),
                "name": row.get("name"),
                "brand": row.get("brand"),
                "architect": row.get("architect"),
                "gc": row.get("gc"),
                "quoteTotal": totals.get(row["_id"], {}).get("grandTotal"),
                "lineCount": _line_count(totals.get(row["_id"])),
            }
            for row in rows
        ]
    }
