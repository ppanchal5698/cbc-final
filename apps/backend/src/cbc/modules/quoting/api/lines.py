"""A bid's quote lines, for the modules and the gate that read or stamp them."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, TypedDict

from cbc.modules.quoting.infrastructure.collections import estimate_lines


class EstimateLineRef(TypedDict, total=False):
    """A stored estimate line, as other modules read it.

    Still the stored document at runtime: a TypedDict converts nothing.
    """

    _id: Any
    projectId: Any
    mark: str
    doorNumber: str
    part: str
    partNumber: str
    division: str
    qty: float
    cost: float
    extended: float


async def list_for_project(project_id: Any, *, limit: int | None = None) -> list[EstimateLineRef]:
    return await estimate_lines().find({"projectId": project_id}).to_list(limit)


async def set_version(project_id: Any, version_id: Any) -> None:
    """Live quote lines belong to this version (estimateVersionId), after a snapshot."""
    await estimate_lines().update_many({"projectId": project_id}, {"$set": {"estimateVersionId": version_id}})


# On a line copied from a prior bid until an estimator keeps it, edits it, or a
# take-off priced on this bid reproduces it. The review holds the proposal on it.
CARRIED = "carried_from_prior"

# What a line says and what it costs, with the decisions behind them (`overrides`
# is how a re-price knows an estimator set a field). Not the prior's drawing
# page, its vendor RFQ or its version: those belong to the other job.
_CARRIED_FIELDS = (
    "lineKey", "part", "manufacturer", "description", "division", "group", "qty", "unit",
    "finish", "openings", "qtyPerOpening", "basis", "notes", "substitutionNote",
    "alternateGroup", "addedByHand", "cost", "margin", "overrideReason", "marginOverridden",
    "sell", "extended", "costSource", "costSourceDetail", "multiplier", "multiplierTier",
    "multiplierEffectiveDate", "priceBookVersion", "lastPoDate", "priceStatus", "listPrice",
    "pricedAt", "marginSnapshot", "costSnapshot", "priceBookSnapshot", "multiplierTierSnapshot",
    "overrides",
)


async def carry_from_prior(project: dict[str, Any], prior: dict[str, Any]) -> None:
    """FR-1d / FR-11: a templated bid starts as a Save As of a prior job's quote.

    Every line arrives flagged, so no row left over from the other job goes out on
    this one unseen ("clear residual rows"). Choosing a different prior replaces
    the lines nobody has kept yet; a bid with lines of its own is refused.
    """
    from fastapi import HTTPException

    from cbc.modules.quoting.api import quote

    current = await estimate_lines().find({"projectId": project["_id"]}, {"flags": 1}).to_list(None)
    own = [line for line in current if CARRIED not in (line.get("flags") or [])]
    if own:
        raise HTTPException(
            409, f"this bid already has {len(own)} quote line(s) of its own; "
            "a past bid can only start a quote that is empty"
        )
    now = datetime.now(timezone.utc)
    copies = [
        {
            **{field: line[field] for field in _CARRIED_FIELDS if field in line},
            "projectId": project["_id"],
            "carriedFrom": prior.get("code"),
            "flags": [*(flag for flag in line.get("flags") or [] if flag != CARRIED), CARRIED],
            "createdAt": now,
            "updatedAt": now,
        }
        async for line in estimate_lines().find({"projectId": prior["_id"]})
    ]
    await estimate_lines().delete_many({"projectId": project["_id"], "flags": CARRIED})
    if copies:
        await estimate_lines().insert_many(copies)
    await quote.persist(project)


async def keep_carried(project_id: Any) -> int:
    """The estimator says the carried lines apply to this job. Returns how many."""
    result = await estimate_lines().update_many(
        {"projectId": project_id, "flags": CARRIED}, {"$pull": {"flags": CARRIED}}
    )
    return result.modified_count


async def set_fields(project_id: Any, key: str, fields: dict[str, Any], *, by: str, reason: str) -> int:
    """A line's fields put back to a version's (FR-14), recorded as an estimator's
    edit so a re-price keeps them."""
    now = datetime.now(timezone.utc)
    result = await estimate_lines().update_one(
        {"projectId": project_id, "lineKey": key},
        {"$set": {**fields, "updatedAt": now},
         "$push": {"overrides": {"at": now, "by": by, "after": fields, "reason": reason}}},
    )
    return result.modified_count


async def delete_by_key(project_id: Any, key: str) -> int:
    result = await estimate_lines().delete_one({"projectId": project_id, "lineKey": key})
    return result.deleted_count


async def restore(project_id: Any, doc: dict[str, Any]) -> None:
    """Put back a line a version still has - a removal the estimator did not accept."""
    await estimate_lines().insert_one({**doc, "projectId": project_id})
