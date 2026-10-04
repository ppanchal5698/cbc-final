"""The door schedule on disk, both ways: what a take-off pass wrote, loaded into
openings; and the estimator's confirmed openings, written back down.

The export carries the estimator's confirmed state down to disk so the next pass
reconciles against it rather than overwriting it.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymongo import InsertOne, UpdateOne

from cbc.modules.extraction.api import openings as extraction_openings
from cbc.modules.extraction.domain.schedule import (
    _identity,
    _normalize_schedule_payload,
    _status_for,
    door_number,
)
from cbc.modules.pricing.api import reference_library
from cbc.modules.projects.api.scope_metadata import import_scope_metadata
from cbc.shared import storage
from cbc.shared.pass_files import distinct_keys, read_json, write_json


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _merge_flags(*groups: list[str] | None) -> list[str]:
    """Preserve order while dropping duplicates."""
    seen: set[str] = set()
    out: list[str] = []
    for group in groups:
        for flag in group or []:
            if flag and flag not in seen:
                seen.add(flag)
                out.append(flag)
    return out


def _opening_finish(item: dict[str, Any]) -> tuple[str | None, list[str]]:
    """Apply the dual-nomenclature crosswalk (NR-3 / Matrix 7.5) on import."""
    normalized = reference_library.normalize_finish_value(item.get("finish"))
    return normalized.get("value"), list(normalized.get("flags") or [])


def _mongo_fields(
    item: dict[str, Any], *, key: str, project_id: Any, payload: dict[str, Any]
) -> dict[str, Any]:
    """One opening as the `openings` collection stores it.

    Lifted out of the import loop so the map can be checked against what the
    parser emits. It was eight fields short and nothing compared the two, so
    `raw_row`, the parsed dimensions and the whole scope verdict reached the
    artifact and stopped there.
    """
    evidence = {
        "note": item.get("evidence_note"),
        "sheet": item.get("sheet") or payload.get("sheet"),
        "row": item.get("row"),
        "confidence": item.get("confidence"),
        "sourceFile": item.get("source_file") or payload.get("source_file"),
        "sourcePage": item.get("source_page"),
        "bbox": item.get("bbox"),
        "pageSize": item.get("page_size"),
        # Cell-level geometry, so a viewer can highlight the one column a
        # value came from rather than the whole row.
        "rowBbox": item.get("row_bbox"),
        "cellBoxes": item.get("cell_boxes"),
    }
    finish, finish_flags = _opening_finish(item)
    keying = item.get("keying")
    if isinstance(keying, str) and keying.strip():
        keying = {"notes": keying.strip()}
    elif not isinstance(keying, dict):
        keying = None
    fields = {
        "mark": door_number(item) or None,
        "doorNumber": (key.split(":", 1)[-1] if key.startswith("mark:") else key) or None,
        "bidRequestId": project_id,
        "description": item.get("description") or item.get("raw_row", ""),
        "size": item.get("size") or item.get("width"),
        # The parsed dimensions, not only the 4-digit shorthand. "3070" is
        # recoverable but it is not what the sheet printed, and an estimator
        # checking a door against a drawing wants the feet and inches.
        "width": item.get("width"),
        "height": item.get("height"),
        "sizeNotation": item.get("size_notation"),
        # The row exactly as it came off the sheet. Everything else here is
        # an interpretation of it, and without it there is nothing to check
        # an interpretation against (NFR-3).
        "rawRow": item.get("raw_row"),
        # Decided in code by `domain.scope_rules`. `flags` carried
        # `out_of_scope_storefront` and nothing else, so the UI could see
        # that a row was excluded but not which rule did it or why.
        "inScope": item.get("in_scope"),
        "scopeRule": item.get("scope_rule"),
        "scopeReason": item.get("scope_reason"),
        "qty": item.get("qty", 1),
        "hwSet": item.get("hardware_set") or item.get("hw_set"),
        "division": item.get("division"),
        "handing": item.get("handing"),
        "finish": finish,
        "fireRating": item.get("fire_rating"),
        "frameType": item.get("frame_type"),
        "wallType": item.get("wall_type"),
        # Derived from wallType before validation, and the bid-alternate tag
        # the opening carries (FR-2). alternate / alternate_group both map here.
        "frameDepth": item.get("frame_depth"),
        "alternateGroup": item.get("alternate") or item.get("alternate_group"),
        "doorType": item.get("door_type") or item.get("type"),
        "doorMaterial": item.get("door_material") or item.get("material"),
        "frameMaterial": item.get("frame_material"),
        "glass": item.get("glass") or item.get("glazing"),
        "manufacturer": item.get("manufacturer"),
        "series": item.get("series"),
        "hardware": item.get("hardware"),
        "notes": item.get("notes") or item.get("comments"),
        "location": item.get("location") or item.get("room_name"),
        "keying": keying,
        "confidence": item.get("confidence"),
        "flags": _merge_flags(item.get("flags"), finish_flags),
        "evidence": evidence,
        "duplicateReason": item.get("duplicate_reason"),
        "updatedAt": _now(),
    }
    return fields


async def import_extraction(
    project: dict[str, Any], *, job: dict[str, Any] | None = None
) -> dict[str, int]:
    """Load `extracted/line_items.json` into `lineItems`.

    Returns counts so the caller can report what a job actually changed.
    Pass `job` to abort without writing when the worker's lease was stolen.
    """
    if job is not None:
        from cbc.modules.ops.api.jobs import holds_lease

        if not await holds_lease(job):
            return {"inserted": 0, "updated": 0, "skipped": 0, "aborted": True}
    slug, project_id = project["slug"], project["_id"]
    raw = read_json(storage.project_dir(slug) / "extracted" / "line_items.json")
    source = storage.project_dir(slug) / "extracted" / "line_items.json"
    if source.exists() and raw is None:
        raise ValueError("extracted/line_items.json is missing or invalid JSON")
    # Create-form autofill must not wait on openings — finishes-only bids still
    # get brand / location / state from the title block.
    await import_scope_metadata(project)

    if not raw:
        return {"inserted": 0, "updated": 0, "skipped": 0}

    payload = _normalize_schedule_payload(raw)

    existing_docs = [
        doc
        for doc in await extraction_openings.list_for_project(
            project_id, sort=[("mark", 1), ("createdAt", 1)]
        )
    ]
    existing_keys = distinct_keys(
        [
            {
                "mark": doc.get("mark"),
                "description": doc.get("description"),
                "raw_row": doc.get("description"),
            }
            for doc in existing_docs
        ],
        _identity,
    )
    existing = {key: doc for key, doc in zip(existing_keys, existing_docs)}

    openings = payload.get("openings", [])
    inserted = updated = skipped = 0
    bulk: list[InsertOne | UpdateOne] = []
    for key, item in zip(distinct_keys(openings, _identity), openings):
        fields = _mongo_fields(
            item, key=key, project_id=project_id, payload=payload
        )

        current = existing.get(key)
        if current is None:
            bulk.append(
                InsertOne(
                    {
                        "projectId": project_id,
                        "status": _status_for(item),
                        "addedByHand": False,
                        "createdAt": _now(),
                        **fields,
                    }
                )
            )
            inserted += 1
        elif current.get("confirmedAt") or current.get("addedByHand"):
            bulk.append(
                UpdateOne(
                    {"_id": current["_id"]},
                    {"$set": {"evidence": fields["evidence"], "updatedAt": _now()}},
                )
            )
            skipped += 1
        else:
            bulk.append(
                UpdateOne(
                    {"_id": current["_id"]},
                    {"$set": {"status": _status_for(item), **fields}},
                )
            )
            updated += 1

    if bulk:
        if job is not None:
            from cbc.modules.ops.api.jobs import holds_lease

            if not await holds_lease(job):
                return {"inserted": 0, "updated": 0, "skipped": 0, "aborted": True}
        await extraction_openings.apply_bulk(bulk)

    return {"inserted": inserted, "updated": updated, "skipped": skipped}


async def export_line_items(project: dict[str, Any]) -> Path:
    """Write the estimator-confirmed state down for Claude's next phase."""
    slug, project_id = project["slug"], project["_id"]
    openings = []
    for doc in await extraction_openings.list_for_project(project_id, sort=[("mark", 1)]):
        if doc.get("status") == "duplicate" and doc.get("duplicateOf"):
            continue
        evidence = doc.get("evidence") or {}
        openings.append(
            {
                "mark": doc.get("mark"),
                "door_number": doc.get("mark"),
                "description": doc.get("description"),
                "size": doc.get("size"),
                "width": doc.get("width"),
                "height": doc.get("height"),
                "size_notation": doc.get("sizeNotation"),
                "raw_row": doc.get("rawRow"),
                "in_scope": doc.get("inScope"),
                "scope_rule": doc.get("scopeRule"),
                "scope_reason": doc.get("scopeReason"),
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
                "door_type": doc.get("doorType"),
                "door_material": doc.get("doorMaterial"),
                "frame_material": doc.get("frameMaterial"),
                "glass": doc.get("glass"),
                "manufacturer": doc.get("manufacturer"),
                "series": doc.get("series"),
                "hardware": doc.get("hardware"),
                "notes": doc.get("notes"),
                "location": doc.get("location"),
                "keying": doc.get("keying"),
                "source_file": evidence.get("sourceFile"),
                "source_page": evidence.get("sourcePage"),
                "bbox": evidence.get("bbox"),
                "page_size": evidence.get("pageSize"),
                "row_bbox": evidence.get("rowBbox"),
                "cell_boxes": evidence.get("cellBoxes"),
                "confidence": doc.get("confidence"),
                "flags": doc.get("flags", []),
                "status": doc.get("status"),
                "confirmed_by": doc.get("confirmedBy"),
                "added_by_hand": doc.get("addedByHand", False),
                # Division 10 counts and FRP geometry. This is the only route
                # they take to pricing now: the pass used to read
                # `div10_takeoff.json` and `frp_takeoff.json` directly, which
                # meant an accessory could be quoted from two places at once.
                "specialty": doc.get("specialty"),
            }
        )

    path = storage.project_dir(slug) / "extracted" / "line_items.json"
    payload = {
        "project": slug,
        "project_code": project.get("code"),
        "exported_at": _now().isoformat(),
        "source": "estimator-confirmed via Ops-Hub",
        "openings": openings,
    }
    await asyncio.to_thread(write_json, path, payload)
    return path
