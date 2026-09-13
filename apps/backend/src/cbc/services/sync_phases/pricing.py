"""Priced lines, in both directions.

Exports carry the estimator's confirmed state back down to disk so the
next pass reconciles against it rather than overwriting it.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from pymongo import InsertOne, UpdateOne

from cbc.db import db
from cbc.services import storage
from cbc.services.sync_phases._common import (
    _content_key,
    _distinct_keys,
    _group_type,
    _lines_in,
    _now,
    _read_json,
    _sane_cost,
    _write_json,
    door_number,
)

log = logging.getLogger("cbc.services.sync")


async def export_line_items(project: dict[str, Any]) -> Path:
    """Write the estimator-confirmed state down for Claude's next phase."""
    slug, project_id = project["slug"], project["_id"]
    openings = []
    async for doc in db.line_items.find({"projectId": project_id}).sort("mark", 1):
        if doc.get("status") == "duplicate" and doc.get("duplicateOf"):
            continue
        evidence = doc.get("evidence") or {}
        openings.append(
            {
                "mark": doc.get("mark"),
                "door_number": doc.get("mark"),
                "description": doc.get("description"),
                "size": doc.get("size"),
                "qty": doc.get("qty", 1),
                "hardware_set": doc.get("hwSet"),
                "division": doc.get("division"),
                "handing": doc.get("handing"),
                "finish": doc.get("finish"),
                "fire_rating": doc.get("fireRating"),
                "frame_type": doc.get("frameType"),
                "wall_type": doc.get("wallType"),
                "frame_depth": doc.get("frameDepth"),
                "alternate": doc.get("alternateGroup"),
                "source_file": evidence.get("sourceFile"),
                "source_page": evidence.get("sourcePage"),
                "bbox": evidence.get("bbox"),
                "page_size": evidence.get("pageSize"),
                "confidence": doc.get("confidence"),
                "flags": doc.get("flags", []),
                "status": doc.get("status"),
                "confirmed_by": doc.get("confirmedBy"),
                "added_by_hand": doc.get("addedByHand", False),
            }
        )

    path = storage.project_dir(slug) / "extracted" / "door_schedule.json"
    payload = {
        "project": slug,
        "project_code": project.get("code"),
        "exported_at": _now().isoformat(),
        "source": "estimator-confirmed via Ops-Hub",
        "openings": openings,
    }
    await asyncio.to_thread(_write_json, path, payload)
    return path
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
        async for doc in db.quote_lines.find({"projectId": project_id})
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
        await db.quote_lines.bulk_write(bulk, ordered=False)

    return {"inserted": inserted, "updated": updated, "skipped": skipped}
async def export_quote_lines(project: dict[str, Any]) -> Path:
    """Write the estimator-approved quote down for the proposal phase."""
    slug, project_id = project["slug"], project["_id"]
    lines = []
    async for doc in db.quote_lines.find({"projectId": project_id}):
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

    quote = await db.quotes.find_one({"projectId": project_id}) or {}
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
