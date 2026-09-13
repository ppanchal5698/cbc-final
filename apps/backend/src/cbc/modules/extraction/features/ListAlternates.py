"""GET /api/projects/{code}/alternates - every line group on a bid, each with its own total.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from cbc.db import db  # ponytail: quote lines and quotes read directly until quoting owns them (step 3.9)
from cbc.modules.extraction.domain.alternates import PENDING_NOTE
from cbc.modules.extraction.infrastructure.collections import openings
from cbc.modules.projects.api.lookup import load
from cbc.modules.pricing.api import pricing

router = APIRouter(prefix="/api/projects/{code}", tags=["alternates"])


@router.get("/alternates")
async def list_alternates(code: str) -> dict[str, Any]:
    """Every line group on this bid, with its own independent total."""
    project = await load(code)
    project_id = project["_id"]

    names = list(project.get("alternates") or [])
    names += await openings().distinct("alternateGroup", {"projectId": project_id})
    names += await db.quote_lines.distinct("alternateGroup", {"projectId": project_id})
    groups = [None] + sorted({n for n in names if n})

    quote = await db.quotes.find_one({"projectId": project_id}) or {}
    state = quote.get("taxJurisdiction") or project.get("state")

    out = []
    for group in groups:
        query = {"projectId": project_id, "alternateGroup": group}
        lines = await db.quote_lines.find(query).to_list(2000)
        totals = pricing.totals(lines, state, quote.get("freight") if group is None else None)
        out.append(
            {
                "name": group,
                "label": group or "Base bid",
                "isBase": group is None,
                "lineItemCount": await openings().count_documents(query),
                "quoteLineCount": len(lines),
                "subtotal": totals["subtotal"],
                "grandTotal": totals["grandTotal"],
                "unpricedLines": totals["unpricedLines"],
            }
        )

    return {"alternates": out, "pending": PENDING_NOTE}
