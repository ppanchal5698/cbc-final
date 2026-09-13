"""A bid's empty create-form fields, filled from the title block a take-off pass read.

Ops-Hub values win: only fields the estimator left empty are filled, and each
one carries the file and page it came from (NFR-3).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from cbc.modules.projects.infrastructure.collections import bid_requests
from cbc.shared import storage
from cbc.shared.pass_files import read_json


def _now() -> datetime:
    return datetime.now(timezone.utc)


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
    raw = read_json(storage.project_dir(slug) / "extracted" / "scope_metadata.json")
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
    await bid_requests().update_one({"_id": project_id}, {"$set": updates})
    return True
