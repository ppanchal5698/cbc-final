"""GET /api/projects/{code}/alternates - the base bid and each alternate, with what accepting it does.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from cbc.modules.extraction.api import openings as extraction_openings
from cbc.modules.projects.api.lookup import load
from cbc.modules.pricing.api import pricing
from cbc.modules.quoting.api import quote as quote_service
from cbc.modules.quoting.domain import alternates
from cbc.modules.quoting.infrastructure.collections import estimate_lines, quotes

router = APIRouter(prefix="/api/projects/{code}", tags=["alternates"])


@router.get("/alternates")
async def list_alternates(code: str) -> dict[str, Any]:
    """Every line group on this bid in the bid form's order: each alternate's kind,
    its own lines' total, what accepting it does to the base bid (FR-14), the base
    and alternates accepted in priority order, and any base line two of them take out."""
    project = await load(code)
    project_id = project["_id"]

    # The alternates named on the create form (FR-1a) and those made on the quote:
    # the form's were stored as `bidAlternates` and read by nothing here.
    names = list(project.get("alternates") or []) + list(project.get("bidAlternates") or [])
    names += await extraction_openings.distinct_groups(project_id)
    names += await estimate_lines().distinct("alternateGroup", {"projectId": project_id})
    names = [name for name in names if name]

    totals, lines = await quote_service.totals_for(project)
    specs = alternates.specs(project.get("alternateSpecs"), names, project.get("bidAlternates"))
    rolled = alternates.rollup(lines, specs)
    quote = await quotes().find_one({"projectId": project_id}) or {}
    state = quote_service.tax_state(project, quote)

    async def group(name: str | None, **fields: Any) -> dict[str, Any]:
        own = [line for line in lines if line.get("alternateGroup") == name]
        figures = pricing.totals(own, state, None)
        return {
            "name": name, "label": name, "isBase": False,
            "lineItemCount": await extraction_openings.count_in_group(project_id, name),
            "quoteLineCount": len(own),
            "subtotal": figures["subtotal"], "grandTotal": figures["grandTotal"],
            "unpricedLines": figures["unpricedLines"],
            **fields,
        }

    out = [{
        "name": None, "label": "Base bid", "isBase": True, "kind": None,
        "lineItemCount": await extraction_openings.count_in_group(project_id, None),
        "quoteLineCount": len(rolled["base"]),
        "subtotal": totals["subtotal"], "grandTotal": totals["grandTotal"],
        "unpricedLines": totals["unpricedLines"],
    }]
    for figure in rolled["alternates"]:
        out.append(await group(
            figure["name"], kind=figure["kind"], priority=figure["priority"], description=figure["description"],
            added=figure["added"], deducted=figure["deducted"], net=figure["net"], withBase=figure["withBase"],
            complete=figure["complete"], takeoff=figure["takeoff"],
        ))
    if alternates.BY_OTHERS_ALTERNATE in names:
        # Out of the bid, not an alternate to it: a filter for the quote screen,
        # never a combination.
        out.append(await group(alternates.BY_OTHERS_ALTERNATE, kind="by_others"))

    return {
        "alternates": out,
        "cumulative": rolled["cumulative"],
        "overlaps": rolled["overlaps"],
        "pending": alternates.PENDING_NOTE,
    }
