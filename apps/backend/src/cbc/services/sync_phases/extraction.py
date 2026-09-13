"""What a take-off pass wrote, into the database."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Any

from pymongo import InsertOne, UpdateOne

from cbc.db import db
from cbc.modules.intake.api import versions as intake_versions
from cbc.services import reference_library, storage
from cbc.services.sync_phases._common import (
    _distinct_keys,
    _identity,
    _normalize_schedule_payload,
    _now,
    _read_json,
    _status_for,
    door_number,
)


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

log = logging.getLogger("cbc.services.sync")


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
    raw = _read_json(storage.project_dir(slug) / "extracted" / "door_schedule.json")
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
        async for doc in db.line_items.find({"projectId": project_id}).sort(
            [("mark", 1), ("createdAt", 1)]
        )
    ]
    existing_keys = _distinct_keys(
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
    for key, item in zip(_distinct_keys(openings, _identity), openings):
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
        await db.line_items.bulk_write(bulk, ordered=False)

    return {"inserted": inserted, "updated": updated, "skipped": skipped}
def _empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def _as_bid_due(value: Any) -> Any:
    """Normalise agent dates onto project.bidDue (UTC midnight)."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        text = value.strip()[:10]
        try:
            return datetime.combine(
                date.fromisoformat(text), datetime.min.time(), tzinfo=timezone.utc
            )
        except ValueError:
            return value
    return value


def _compose_location(raw: dict[str, Any], updates: dict[str, Any], project: dict[str, Any]) -> str | None:
    """Build create-dialog `location` from title-block parts when still empty."""
    if not _empty(project.get("location")) or not _empty(updates.get("location")):
        return None
    if raw.get("location"):
        return str(raw["location"]).strip() or None
    address = updates.get("address") or project.get("address") or raw.get("address")
    city = updates.get("city") or project.get("city") or raw.get("city")
    state = updates.get("state") or project.get("state") or raw.get("state")
    parts = [str(p).strip() for p in (address, city, state) if p and str(p).strip()]
    return ", ".join(parts) if parts else None


def _field_source_entry(
    raw: dict[str, Any],
    *,
    source_keys: list[str],
    default_page: Any = None,
) -> dict[str, Any] | None:
    """Provenance for one autofilled Ops-Hub field (NFR-3)."""
    sources = raw.get("field_sources") if isinstance(raw.get("field_sources"), dict) else {}
    entry: dict[str, Any] = {}
    for key in source_keys:
        blob = sources.get(key)
        if isinstance(blob, dict) and blob:
            entry = dict(blob)
            break
    files = raw.get("source_files") if isinstance(raw.get("source_files"), list) else []
    page = entry.get("source_page") or entry.get("page") or default_page or raw.get("source_page")
    path = entry.get("source_file") or entry.get("file") or (files[0] if files else None)
    excerpt = entry.get("excerpt") or entry.get("quote") or entry.get("text")
    if page is None and path is None and not excerpt:
        return {
            "filledBy": "claude",
            "filledAt": _now(),
            "fromPdf": True,
        }
    out: dict[str, Any] = {
        "filledBy": "claude",
        "filledAt": _now(),
        "fromPdf": True,
    }
    if path:
        out["sourceFile"] = str(path)
    if page is not None:
        try:
            out["sourcePage"] = int(page)
        except (TypeError, ValueError):
            out["sourcePage"] = page
    if excerpt:
        out["excerpt"] = str(excerpt).strip()[:240]
    return out


async def import_scope_metadata(project: dict[str, Any]) -> bool:
    """PATCH project fields from extracted/scope_metadata.json when present.

    Ops-Hub values win: only fill fields the estimator left empty. Mode and
    bidAlternates follow the same rule so a create-form choice is not clobbered.
    Autofilled values also land in `intakeFieldSources` so the job record can
    prove where each value came from.
    """
    slug, project_id = project["slug"], project["_id"]
    raw = _read_json(storage.project_dir(slug) / "extracted" / "scope_metadata.json")
    if not raw or not isinstance(raw, dict):
        return False

    # bid_due_date → bidDue (project schema / UI / index). Never bidDueDate.
    field_map = {
        "project_name": "name",
        "name": "name",
        "brand": "brand",
        "address": "address",
        "city": "city",
        "state": "state",
        "location": "location",
        "architect": "architect",
        "gc": "gc",
        "initiator": "initiator",
        "bid_due_date": "bidDue",
        "project_number": "projectNumber",
    }
    # Map Ops-Hub keys back to agent keys for field_sources lookup.
    source_keys_for = {
        "name": ["project_name", "name"],
        "brand": ["brand"],
        "address": ["address"],
        "city": ["city"],
        "state": ["state"],
        "location": ["location", "city", "address"],
        "architect": ["architect"],
        "gc": ["gc"],
        "initiator": ["initiator"],
        "bidDue": ["bid_due_date", "bidDue"],
        "projectNumber": ["project_number", "projectNumber"],
        "mode": ["mode"],
        "bidAlternates": ["bid_alternates", "bidAlternates"],
    }

    updates: dict[str, Any] = {}
    filled_keys: list[str] = []
    for source_key, target_key in field_map.items():
        value = raw.get(source_key)
        if value is not None and value != "" and _empty(project.get(target_key)):
            if target_key == "bidDue":
                value = _as_bid_due(value)
            if target_key == "state" and isinstance(value, str):
                value = value.strip().upper()[:2]
            updates[target_key] = value
            filled_keys.append(target_key)

    location = _compose_location(raw, updates, project)
    if location and _empty(project.get("location")) and "location" not in updates:
        updates["location"] = location
        filled_keys.append("location")

    mode = raw.get("mode")
    if mode in ("one_off", "templated") and _empty(project.get("mode")):
        updates["mode"] = mode
        filled_keys.append("mode")

    alts = raw.get("bid_alternates")
    alts_added = False
    if isinstance(alts, list):
        current = [str(a).strip() for a in (project.get("bidAlternates") or []) if str(a).strip()]
        merged = list(current)
        for alt in alts:
            name = str(alt).strip() if not isinstance(alt, dict) else str(
                alt.get("name") or alt.get("label") or ""
            ).strip()
            if name and name not in merged:
                merged.append(name)
                alts_added = True
        if merged != current:
            updates["bidAlternates"] = merged
            if alts_added:
                filled_keys.append("bidAlternates")

    if not updates:
        return False

    existing_sources = dict(project.get("intakeFieldSources") or {})
    for key in filled_keys:
        entry = _field_source_entry(
            raw,
            source_keys=source_keys_for.get(key, [key]),
            default_page=raw.get("source_page"),
        )
        if entry:
            existing_sources[key] = entry
    if existing_sources:
        updates["intakeFieldSources"] = existing_sources

    updates["updatedAt"] = _now()
    await db.projects.update_one({"_id": project_id}, {"$set": updates})
    return True
async def import_addendum(project: dict[str, Any], job: dict[str, Any]) -> dict[str, int]:
    """Load review/addendum_diff.json onto the version Claude was reading."""
    slug = project["slug"]
    payload = _read_json(storage.project_dir(slug) / "review" / "addendum_diff.json")
    source = storage.project_dir(slug) / "review" / "addendum_diff.json"
    if source.exists() and payload is None:
        raise ValueError("review/addendum_diff.json is missing or invalid JSON")
    if not payload:
        return {"added": 0, "removed": 0, "changed": 0}

    version = (job.get("payload") or {}).get("version")
    if version is None:
        raise ValueError("ingest_addendum job missing payload.version")

    recorded = await intake_versions.record_addendum_diff(project["_id"], int(version), payload)
    if not recorded:
        raise ValueError(f"version {version} not found for addendum diff import")

    return {
        "added": len(payload.get("added") or []),
        "removed": len(payload.get("removed") or []),
        "changed": len(payload.get("changed") or []),
    }
