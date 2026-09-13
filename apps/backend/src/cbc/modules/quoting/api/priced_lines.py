"""Priced lines in both directions: a pricing pass's lines loaded in, the approved quote written out.

Exports carry the estimator's confirmed state back down to disk so the next pass
reconciles against it rather than overwriting it.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from pymongo import InsertOne, UpdateOne

from cbc.modules.quoting.infrastructure.collections import estimate_lines, quotes
from cbc.services import storage  # ponytail: legacy kernel; the file tree moves to shared/ in Phase 4
# ponytail: legacy kernel; the sync helpers move with the pricing job's slice (Phase 4)
from cbc.services.sync_phases._common import (
    _content_key,
    _distinct_keys,
    _group_type,
    _lines_in,
    _now,
    _read_json,
    _sane_cost,
    _write_json,
)


async def import_quote_lines(
    project: dict[str, Any], *, job: dict[str, Any] | None = None
) -> dict[str, int]:
    """Load `priced/line_items.json` into `quoteLines`."""
    if job is not None:
        from cbc.modules.ops.api.jobs import holds_lease

        if not await holds_lease(job):
            return {"inserted": 0, "updated": 0, "skipped": 0, "aborted": True}
    slug, project_id = project["slug"], project["_id"]
    payload = _read_json(storage.project_dir(slug) / "priced" / "line_items.json")
    source = storage.project_dir(slug) / "priced" / "line_items.json"
    if source.exists() and payload is None:
        raise ValueError("priced/line_items.json is missing or invalid JSON")
    if not payload:
        return {"inserted": 0, "updated": 0, "skipped": 0}

    existing = {
        doc.get("lineKey"): doc
        async for doc in estimate_lines().find({"projectId": project_id})
    }

    # `line_id` when Claude supplied one, otherwise derived from the line's own
    # content. The previous fallback keyed on list position, so re-ordering a
    # re-priced quote gave every line a new key and duplicated the lot.
    priced_lines = _lines_in(payload, "priced/line_items.json", "lines")
    inserted = updated = skipped = 0
    bulk: list[InsertOne | UpdateOne] = []
    for key, line in zip(_distinct_keys(priced_lines, _content_key), priced_lines):
        cost, flags = _sane_cost(line)
        fields = {
            "lineKey": key,
            "part": line.get("part_number") or line.get("part"),
            "description": line.get("description", ""),
            "division": line.get("division") or line.get("group_type"),
            "group": line.get("group"),
            "qty": line.get("quantity", 1),
            "cost": cost,
            "margin": line.get("margin"),
            "sell": line.get("sale_ea"),
            "extended": line.get("ext_price"),
            "basis": line.get("basis") or "Book price",
            "costSource": line.get("cost_source"),
            "costSourceDetail": line.get("cost_source_detail"),
            "multiplier": line.get("multiplier"),
            "multiplierTier": line.get("multiplier_tier"),
            "multiplierEffectiveDate": line.get("multiplier_effective_date"),
            "priceBookVersion": line.get("price_book_version"),
            "sourcePage": line.get("source_page"),
            "priceStatus": line.get("price_status"),
            "flags": flags,
            "updatedAt": _now(),
        }

        current = existing.get(key)
        if current is None:
            bulk.append(
                InsertOne(
                    {
                        "projectId": project_id,
                        "addedByHand": False,
                        "marginOverridden": False,
                        "createdAt": _now(),
                        **fields,
                    }
                )
            )
            inserted += 1
        elif current.get("marginOverridden") or current.get("addedByHand"):
            bulk.append(
                UpdateOne(
                    {"_id": current["_id"]},
                    {
                        "$set": {
                            key_: fields[key_]
                            for key_ in (
                                "costSource",
                                "costSourceDetail",
                                "multiplier",
                                "multiplierTier",
                                "multiplierEffectiveDate",
                                "priceBookVersion",
                                "sourcePage",
                                "updatedAt",
                            )
                        }
                    },
                )
            )
            skipped += 1
        else:
            bulk.append(UpdateOne({"_id": current["_id"]}, {"$set": fields}))
            updated += 1

    if bulk:
        if job is not None:
            from cbc.modules.ops.api.jobs import holds_lease

            if not await holds_lease(job):
                return {"inserted": 0, "updated": 0, "skipped": 0, "aborted": True}
        await estimate_lines().bulk_write(bulk, ordered=False)

    return {"inserted": inserted, "updated": updated, "skipped": skipped}


async def export_quote_lines(project: dict[str, Any]) -> Path:
    """Write the estimator-approved quote down for the proposal phase."""
    slug, project_id = project["slug"], project["_id"]
    lines = []
    async for doc in estimate_lines().find({"projectId": project_id}):
        lines.append(
            {
                "line_id": doc.get("lineKey") or str(doc["_id"]),
                "group": doc.get("group") or doc.get("division") or "Other",
                "group_type": _group_type(doc.get("division")),
                "part_number": doc.get("part"),
                "description": doc.get("description"),
                "division": doc.get("division"),
                "quantity": doc.get("qty", 1),
                "cost": doc.get("cost"),
                "margin": doc.get("margin"),
                "sale_ea": doc.get("sell"),
                "ext_price": doc.get("extended"),
                "cost_source": doc.get("costSource"),
                "cost_source_detail": doc.get("costSourceDetail"),
                "multiplier": doc.get("multiplier"),
                "multiplier_tier": doc.get("multiplierTier"),
                "multiplier_effective_date": doc.get("multiplierEffectiveDate"),
                "price_book_version": doc.get("priceBookVersion"),
                "source_page": doc.get("sourcePage"),
                "price_status": doc.get("priceStatus"),
                "added_by_hand": doc.get("addedByHand", False),
                "flags": doc.get("flags", []),
            }
        )

    quote = await quotes().find_one({"projectId": project_id}) or {}
    path = storage.project_dir(slug) / "priced" / "line_items.json"
    payload = {
        "generated_by": "estimator-approved via Ops-Hub",
        "quote_number": quote.get("quoteNumber") or f"Q-{project.get('code', '')}",
        "quote_date": _now().date().isoformat(),
        "project": {
            "name": project.get("name"),
            "location": project.get("location"),
            "state": project.get("state"),
            "architect": project.get("architect"),
        },
        "customer": {"gc": project.get("gc"), "initiator": project.get("initiator")},
        "estimator": {"name": quote.get("estimatorName")},
        "lines": lines,
    }
    await asyncio.to_thread(_write_json, path, payload)
    return path
