"""Quote - editable cost, margin and quantity, with totals recomputed on the spot.

Every number here comes from `calc-engine` through `api/services/pricing.py`.
Nothing in this module does arithmetic on money.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, HTTPException

from cbc.db import db
from cbc.shared.mongo import oid, serialise
from cbc.shared.auth import Actor
from cbc.schemas import QuoteLineCreate, QuoteLineUpdate, QuoteSettings
from cbc.http.projects_access import load
from cbc.http.pipeline_jobs import enqueue_pipeline
from cbc.modules.ops.api import audit
from cbc.services import feedback, freshness as freshness_settings, jobs, quote as quote_service, sync

router = APIRouter(prefix="/api/projects/{code}/quote", tags=["quote"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _lines(project_id) -> list[dict[str, Any]]:
    return await quote_service.lines_for(project_id)


def _lapsed(line: dict[str, Any], stale_days: int) -> bool:
    """True when the sheet this cost came from is past the review window.

    A lapsed price is not wrong, but it is unverified - the estimator decides.
    """
    effective = line.get("multiplierEffectiveDate")
    if not effective:
        return False
    try:
        return (date.today() - date.fromisoformat(str(effective))).days > stale_days
    except ValueError:
        return False


async def _recompute(project: dict[str, Any], actor: str = "system") -> dict[str, Any]:
    """Re-price, store, and return the totals. Only for routes that change something."""
    return await quote_service.persist(project)


@router.get("")
async def get_quote(code: str) -> dict[str, Any]:
    project = await load(code)
    # Computed, not stored. This is a GET; it used to write a row per line and
    # upsert the totals on every page load and every four-second poll.
    totals, raw = await quote_service.totals_for(project)
    bands = await freshness_settings.load()
    lines = [
        {**serialise(line), "lapsed": _lapsed(line, bands.catalog_stale_days)}
        for line in raw
    ]

    groups: dict[str, dict[str, Any]] = {}
    for line in lines:
        key = line.get("division") or "Other"
        group = groups.setdefault(key, {"division": key, "lines": [], "subtotal": 0.0})
        group["lines"].append(line)
        group["subtotal"] = round(group["subtotal"] + (line.get("extended") or 0), 2)

    quote = await db.quotes.find_one({"projectId": project["_id"]})
    edited = [line for line in lines if line.get("marginOverridden") or line.get("addedByHand")]

    return {
        "quote": serialise(quote),
        "groups": sorted(groups.values(), key=lambda g: g["division"]),
        "totals": totals,
        "lineCount": len(lines),
        "edited": {
            "count": len(edited),
            "firstId": edited[0]["id"] if edited else None,
        },
        "lapsedCount": sum(1 for line in lines if line["lapsed"]),
        "reviewWindowMonths": bands.catalog_stale_months,
    }


@router.patch("/settings")
async def update_settings(code: str, body: QuoteSettings, actor: Actor) -> dict:
    project = await load(code)
    changes = body.model_dump(exclude_unset=True)
    await db.quotes.update_one(
        {"projectId": project["_id"]},
        {"$set": {**changes, "updatedAt": _now()}, "$setOnInsert": {"createdAt": _now()}},
        upsert=True,
    )
    await audit.record("quote.settings", actor, {"projectId": project["_id"]}, after=changes)
    return {"totals": await _recompute(project, actor)}


@router.post("/lines", status_code=201)
async def add_line(code: str, body: QuoteLineCreate, actor: Actor) -> dict:
    project = await load(code)
    payload = body.model_dump(exclude_none=True)

    if body.productId:
        product = await db.products.find_one({"_id": oid(body.productId)})
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
    result = await db.quote_lines.insert_one(document)
    await audit.record(
        "quote.line_added",
        actor,
        {"projectId": project["_id"], "quoteLineId": result.inserted_id},
        after=payload.get("description"),
    )
    totals = await _recompute(project, actor)
    return {"line": serialise(await db.quote_lines.find_one({"_id": result.inserted_id})), "totals": totals}


@router.patch("/lines/{line_id}")
async def update_line(
    code: str, line_id: str, body: QuoteLineUpdate, actor: Actor
) -> dict:
    project = await load(code)
    line = await db.quote_lines.find_one({"_id": oid(line_id), "projectId": project["_id"]})
    if not line:
        raise HTTPException(404, "quote line not found")

    changes = body.model_dump(exclude_unset=True)
    reason = changes.pop("overrideReason", None)
    if not changes:
        return {"line": serialise(line), "totals": await _recompute(project, actor)}

    override = {
        "at": _now(),
        "by": actor,
        "before": {key: line.get(key) for key in changes},
        "after": changes,
        "reason": reason,
    }
    # FR-13: what the copilot proposed, what the estimator chose instead, and
    # how confident it had been. Recorded before the write, so `before` is still
    # the copilot's value rather than the correction.
    await feedback.record_edits(
        bid_request_id=project["_id"],
        changes=changes,
        before=line,
        actor=actor,
        estimate_line_id=line["_id"],
        reason=reason,
    )

    update: dict[str, Any] = {**changes, "updatedAt": _now()}
    if "margin" in changes:
        update["marginOverridden"] = True
        update["overrideReason"] = reason

    await db.quote_lines.update_one(
        {"_id": line["_id"]}, {"$set": update, "$push": {"overrides": override}}
    )
    await audit.record(
        "quote.line_edit",
        actor,
        {"projectId": project["_id"], "quoteLineId": line["_id"]},
        before=override["before"],
        after=changes,
        note=reason,
    )

    totals = await _recompute(project, actor)
    return {"line": serialise(await db.quote_lines.find_one({"_id": line["_id"]})), "totals": totals}


@router.delete("/lines/{line_id}")
async def delete_line(code: str, line_id: str, actor: Actor) -> dict:
    project = await load(code)
    line = await db.quote_lines.find_one({"_id": oid(line_id), "projectId": project["_id"]})
    if not line:
        raise HTTPException(404, "quote line not found")

    await db.quote_lines.delete_one({"_id": line["_id"]})
    await audit.record(
        "quote.line_delete",
        actor,
        {"projectId": project["_id"], "quoteLineId": line["_id"]},
        before=line.get("description"),
    )
    return {"totals": await _recompute(project, actor)}


@router.post("/continue-to-proposal")
async def continue_to_proposal(code: str, actor: Actor) -> dict:
    """Phase boundary: write the approved quote down, then enqueue the proposal build."""
    project = await load(code)
    await _recompute(project, actor)
    await sync.export_quote_lines(project)

    job = await enqueue_pipeline("build_proposal", project["_id"], actor=actor)
    await audit.record("project.continue_to_proposal", actor, {"projectId": project["_id"]})
    return {"job": serialise(job)}
