"""POST /api/projects/{code}/quote/lines - add a priced line by hand, optionally from a catalog part.
"""
from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter

from cbc.modules.catalog.api import products as catalog_products
from cbc.modules.ops.api import audit
from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.api import quote as quote_service
from cbc.modules.quoting.domain.quotes import QuoteLineCreate
from cbc.modules.quoting.infrastructure.collections import estimate_lines
from cbc.shared.auth import Actor
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/projects/{code}/quote", tags=["quote"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/lines", status_code=201)
async def add_line(code: str, body: QuoteLineCreate, actor: Actor) -> dict:
    project = await load(code)
    payload = body.model_dump(exclude_none=True)

    if body.productId:
        product = await catalog_products.get(body.productId)
        if product:
            payload.setdefault("part", product.get("part"))
            payload.setdefault("description", product.get("description", ""))
            payload.setdefault("division", product.get("division"))
            payload.setdefault("cost", product.get("cost"))
            payload["basis"] = f"Catalog · {product.get('priceBook') or 'manual'}"
            payload["costSource"] = "BOOK_PRICE"
            payload.pop("productId", None)

    document = {
        # Every priced field exists from the start, even when unpriced, so a
        # consumer never has to guess whether a missing key means zero or unknown.
        "sell": None,
        "extended": None,
        "margin": None,
        "cost": None,
        **payload,
        "projectId": project["_id"],
        # Unique, not merely time-ordered: at second resolution two lines added
        # in the same second shared a key, and the next sync collapsed them.
        "lineKey": f"hand-{ObjectId()}",
        "addedByHand": True,
        "marginOverridden": False,
        "flags": [],
        "createdAt": _now(),
    }
    result = await estimate_lines().insert_one(document)
    await audit.record(
        "quote.line_added",
        actor,
        {"projectId": project["_id"], "quoteLineId": result.inserted_id},
        after=payload.get("description"),
    )
    totals = await quote_service.persist(project)
    return {"line": serialise(await estimate_lines().find_one({"_id": result.inserted_id})), "totals": totals}
