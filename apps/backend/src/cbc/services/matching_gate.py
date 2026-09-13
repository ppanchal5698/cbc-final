"""Apply FR-4 matching rules to openings after a pricing pass.

`cbc.domain.matching` is pure. This module loads openings + catalog candidates
and persists `ratingConflict` / `ratingMissing` / `matchCandidates`.
"""
from __future__ import annotations

from typing import Any

from cbc.modules.catalog.api import products as catalog_products
from cbc.modules.extraction.api import openings as extraction_openings
from cbc.modules.quoting.api import lines as quoting_lines
from cbc.domain import matching


async def apply_to_project(project: dict[str, Any], *, limit: int = 5000) -> dict[str, int]:
    """Judge each opening against catalog rows that share a part family.

    When an opening already carries a matched part on a quote line, that part is
    the only candidate. Otherwise the opening is flagged ratingMissing when it
    has no fire rating to enforce.
    """
    project_id = project["_id"]
    openings = await extraction_openings.list_for_project(project_id, limit=limit)
    lines: dict[Any, dict[str, Any]] = {}
    for line in await quoting_lines.list_for_project(project_id):
        lines[line.get("mark") or line.get("doorNumber")] = line

    flagged = 0
    for opening in openings:
        mark = opening.get("mark") or opening.get("doorNumber")
        line = lines.get(mark) or {}
        part = line.get("part") or line.get("partNumber")
        candidates: list[dict[str, Any]] = []
        if part:
            for product in await catalog_products.by_part(part, limit=20):
                candidates.append(
                    {
                        "id": str(product.get("_id")),
                        "part": product.get("part"),
                        "fire_rating": product.get("fireRating") or product.get("rating"),
                        "handing": product.get("handing"),
                        "finish": product.get("finish"),
                        "description": product.get("description"),
                    }
                )
        opening_view = {
            **opening,
            "fire_rating": opening.get("fire_rating") or opening.get("fireRating"),
        }
        result = matching.candidates(opening_view, candidates)
        update = {
            "ratingConflict": result["ratingConflict"],
            "ratingMissing": result["ratingMissing"],
            "matchCandidates": result["matchCandidates"],
        }
        if result["ratingConflict"] or result["ratingMissing"]:
            flagged += 1
        await extraction_openings.update_fields(opening["_id"], update)

    return {"openings": len(openings), "flagged": flagged}
