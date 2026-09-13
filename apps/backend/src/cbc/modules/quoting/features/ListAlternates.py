"""GET /api/projects/{code}/alternates - every line group on a bid, each with its own total.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from cbc.modules.extraction.api import openings as extraction_openings
from cbc.modules.projects.api.lookup import load
from cbc.modules.pricing.api import pricing
from cbc.modules.quoting.domain.alternates import PENDING_NOTE
from cbc.modules.quoting.infrastructure.collections import estimate_lines, quotes

router = APIRouter(prefix="/api/projects/{code}", tags=["alternates"])


@router.get("/alternates")
async def list_alternates(code: str) -> dict[str, Any]:
    """Every line group on this bid, with its own independent total."""
    project = await load(code)
    project_id = project["_id"]

    names = list(project.get("alternates") or [])
    names += await extraction_openings.distinct_groups(project_id)
    names += await estimate_lines().distinct("alternateGroup", {"projectId": project_id})
    groups = [None] + sorted({n for n in names if n})

    quote = await quotes().find_one({"projectId": project_id}) or {}
    state = quote.get("taxJurisdiction") or project.get("state")

    out = []
    for group in groups:
        query = {"projectId": project_id, "alternateGroup": group}
        lines = await estimate_lines().find(query).to_list(2000)
        totals = pricing.totals(lines, state, quote.get("freight") if group is None else None)
        out.append(
            {
                "name": group,
                "label": group or "Base bid",
                "isBase": group is None,
                "lineItemCount": await extraction_openings.count_in_group(project_id, group),
                "quoteLineCount": len(lines),
                "subtotal": totals["subtotal"],
                "grandTotal": totals["grandTotal"],
                "unpricedLines": totals["unpricedLines"],
            }
        )

    return {"alternates": out, "pending": PENDING_NOTE}
