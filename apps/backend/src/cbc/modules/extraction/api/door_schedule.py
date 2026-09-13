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
from cbc.services import storage  # ponytail: legacy kernel; where a project's tree lives, until storage moves to shared
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


async def import_extraction(
    project: dict[str, Any], *, job: dict[str, Any] | None = None
) -> dict[str, int]:
    """Load `extracted/door_schedule.json` into `lineItems`.

    Returns counts so the caller can report what a job actually changed.
    Pass `job` to abort without writing when the worker's lease was stolen.
    """
    if job is not None:
        from cbc.modules.ops.api.jobs import holds_lease

        if not await holds_lease(job):
            return {"inserted": 0, "updated": 0, "skipped": 0, "aborted": True}
    slug, project_id = project["slug"], project["_id"]
    raw = read_json(storage.project_dir(slug) / "extracted" / "door_schedule.json")
    source = storage.project_dir(slug) / "extracted" / "door_schedule.json"
    if source.exists() and raw is None:
        raise ValueError("extracted/door_schedule.json is missing or invalid JSON")
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
        evidence = {
            "note": item.get("evidence_note"),
            "sheet": item.get("sheet") or payload.get("sheet"),
            "row": item.get("row"),
            "confidence": item.get("confidence"),
            "sourceFile": item.get("source_file") or payload.get("source_file"),
            "sourcePage": item.get("source_page"),
            "bbox": item.get("bbox"),
            "pageSize": item.get("page_size"),
        }
        finish, finish_flags = _opening_finish(item)
        fields = {
            "mark": door_number(item) or None,
            "doorNumber": (key.split(":", 1)[-1] if key.startswith("mark:") else key) or None,
            "bidRequestId": project_id,
            "description": item.get("description") or item.get("raw_row", ""),
            "size": item.get("size") or item.get("width"),
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
            "confidence": item.get("confidence"),
            "flags": _merge_flags(item.get("flags"), finish_flags),
            "evidence": evidence,
            "duplicateReason": item.get("duplicate_reason"),
            "updatedAt": _now(),
        }

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
                    {"$set": {"evidence": evidence, "updatedAt": _now()}},
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
    await asyncio.to_thread(write_json, path, payload)
    return path
