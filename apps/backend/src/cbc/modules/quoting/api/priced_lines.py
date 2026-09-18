"""Priced lines in both directions: a pricing pass's lines loaded in, the approved quote written out.

Exports carry the estimator's confirmed state back down to disk so the next pass
reconciles against it rather than overwriting it.
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymongo import DeleteOne, InsertOne, UpdateOne

from cbc.modules.quoting.infrastructure.collections import estimate_lines, quotes
from cbc.shared import storage
from cbc.shared.pass_files import distinct_keys, read_json, write_json


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _lines_in(payload: dict[str, Any] | list[Any], filename: str, key: str) -> list[Any]:
    """The records in a priced artifact, whether or not they came wrapped.

    A run is asked for `{"lines": [...]}` and writes a bare array about as often.
    The door-schedule path has accepted both since early on; the priced path did
    not, so a full pipeline that had completed all six phases and written a whole
    quote failed on `'list' object has no attribute 'get'` at the very last step.

    Agents also name the array `line_items` (matching the filename). Taking either
    shape loses no information and no check: every line still goes through
    validation.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        rows = payload.get(key)
        if isinstance(rows, list) and rows:
            return rows
        alt = payload.get("line_items") if key == "lines" else payload.get("lines")
        if isinstance(alt, list):
            return alt
        return rows if isinstance(rows, list) else []
    raise ValueError(f"{filename} must be a JSON object or an array")


def _sane_cost(line: dict[str, Any]) -> tuple[float | None, list[str]]:
    """A cost Claude wrote, or None with a flag saying why it was not taken.

    The API schema bounds what an estimator can type, but a pipeline run writes
    straight into Mongo. A negative or non-numeric cost is not priceable, and
    NFR-2 says an unusable value is flagged rather than guessed at - so it lands
    as unpriced with a reason instead of as a number nothing can divide by.
    """
    raw = line.get("cost")
    flags = list(line.get("flags") or [])
    if raw is None:
        return None, flags
    try:
        cost = float(raw)
    except (TypeError, ValueError):
        return None, flags + [f"unreadable cost {raw!r} - priced manually"]
    if cost < 0:
        return None, flags + [f"negative cost {cost} - priced manually"]
    return cost, flags


def _content_key(line: dict[str, Any]) -> str:
    if line.get("line_id"):
        return str(line["line_id"])
    material = "|".join(
        str(line.get(field) or "")
        for field in ("part_number", "part", "description", "division")
    ).strip().lower()
    return "auto:" + hashlib.sha1(material.encode("utf-8")).hexdigest()[:16]


def _group_type(division: str | None) -> str:
    if not division:
        return "door"
    if division.startswith("10"):
        return "accessories"
    if division.startswith("06"):
        return "frp"
    return "door"


async def import_quote_lines(
    project: dict[str, Any], *, job: dict[str, Any] | None = None
) -> dict[str, int]:
    """Load `priced/line_items.json` into `quoteLines`."""
    if job is not None:
        from cbc.modules.ops.api.jobs import holds_lease

        if not await holds_lease(job):
            return {"inserted": 0, "updated": 0, "skipped": 0, "removed": 0, "aborted": True}
    slug, project_id = project["slug"], project["_id"]
    payload = read_json(storage.project_dir(slug) / "priced" / "line_items.json")
    source = storage.project_dir(slug) / "priced" / "line_items.json"
    if source.exists() and payload is None:
        raise ValueError("priced/line_items.json is missing or invalid JSON")
    if not payload:
        return {"inserted": 0, "updated": 0, "skipped": 0, "removed": 0}

    existing = {
        doc.get("lineKey"): doc
        async for doc in estimate_lines().find({"projectId": project_id})
    }

    # `line_id` when Claude supplied one, otherwise derived from the line's own
    # content. The previous fallback keyed on list position, so re-ordering a
    # re-priced quote gave every line a new key and duplicated the lot.
    priced_lines = _lines_in(payload, "priced/line_items.json", "lines")
    if not priced_lines:
        # Never wipe Mongo estimateLines with an empty agent shell.
        return {"inserted": 0, "updated": 0, "skipped": len(existing), "removed": 0}

    inserted = updated = skipped = 0
    seen_keys: set[Any] = set()
    bulk: list[InsertOne | UpdateOne | DeleteOne] = []
    for key, line in zip(distinct_keys(priced_lines, _content_key), priced_lines):
        seen_keys.add(key)
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

    # Lines the new pricing pass no longer produces. Without this the collection
    # only ever grew: re-pricing a bid that dropped a line left the old row in
    # `estimateLines` and it went on to the quote, so one re-run carried 26 rows
    # that pricing had already discarded.
    #
    # A hand-added line is the estimator's own and is never removed - there is no
    # priced row to regenerate it from, so deleting it would destroy their work.
    # Everything else is derived, and derived rows follow their source.
    removed = 0
    for key, current in existing.items():
        if key in seen_keys or current.get("addedByHand"):
            continue
        bulk.append(DeleteOne({"_id": current["_id"]}))
        removed += 1

    if bulk:
        if job is not None:
            from cbc.modules.ops.api.jobs import holds_lease

            if not await holds_lease(job):
                return {"inserted": 0, "updated": 0, "skipped": 0, "removed": 0, "aborted": True}
        await estimate_lines().bulk_write(bulk, ordered=False)

    return {
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "removed": removed,
    }


async def export_quote_lines(project: dict[str, Any], *, allow_empty: bool = False) -> Path:
    """Write the estimator-approved quote down for the proposal phase.

    An empty Mongo collection must not erase an unimported pricing pass.
    Only an explicit estimator deletion may authorize an empty replacement.
    """
    slug, project_id = project["slug"], project["_id"]
    path = storage.project_dir(slug) / "priced" / "line_items.json"
    existing = read_json(path)
    if path.exists() and existing is None:
        raise ValueError("priced/line_items.json is invalid JSON; refusing to overwrite it")
    existing_rows = _lines_in(existing or {}, "priced/line_items.json", "lines")
    previous = dict(zip(distinct_keys(existing_rows, _content_key), existing_rows))
    lines = []
    async for doc in estimate_lines().find({"projectId": project_id}):
        lines.append(
            {
                # Keep source notes/evidence for surviving rows; stored edits win.
                **previous.get(doc.get("lineKey"), {}),
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

    if not lines and existing_rows and not allow_empty:
        # Keep Claude's priced file; Mongo never absorbed it.
        return path

    quote = await quotes().find_one({"projectId": project_id}) or {}
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
    await asyncio.to_thread(write_json, path, payload)
    return path
