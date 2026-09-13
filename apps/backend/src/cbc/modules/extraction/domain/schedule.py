"""The door schedule a take-off pass writes: the shapes it arrives in, a row's identity, the status it lands in.

Pure rules, shared by the importer (extraction.api.door_schedule) and the
measurements taken off the sheet (extraction.infrastructure.geometry).
"""
from __future__ import annotations

from typing import Any

from cbc.modules.pricing.api.confidence import CONFIDENCE_FLOOR


def _normalize_schedule_payload(payload: dict[str, Any] | list[Any]) -> dict[str, Any]:
    """Accept legacy shapes and field aliases before import."""
    if isinstance(payload, list):
        payload = {"openings": payload}
    if not isinstance(payload, dict):
        raise ValueError("extracted/door_schedule.json must be a JSON object or openings array")

    # `lines` is the key the priced artifact uses, and a run that writes both
    # files in one pass reaches for it here too - it wrote a complete schedule,
    # every opening carrying page_size, confidence and flags, under `lines`, and
    # the import read zero openings and failed the whole pipeline. The file is
    # the door schedule whichever word wraps the array, so take either. Field
    # aliases below have worked this way all along.
    if "openings" not in payload and isinstance(payload.get("lines"), list):
        payload = {**payload, "openings": payload["lines"]}

    openings = []
    for item in payload.get("openings", []):
        if not isinstance(item, dict):
            continue
        if item.get("hardware_set") is None and item.get("hw_set") is not None:
            item = {**item, "hardware_set": item["hw_set"]}
        if item.get("door_number") is None and item.get("mark"):
            item = {**item, "door_number": item["mark"]}
        openings.append(item)
    return {**payload, "openings": openings}


def door_number(item: dict[str, Any]) -> str:
    """The grouping key, whichever of the two names it arrived under.

    `door_number` is what the parser, the agents and the validator emit; `mark` is
    what the Mongo document calls it. Two names for the key the whole quote groups
    by is a standing trap - it is read here, once, so nothing downstream has to
    guess which one is populated.
    """
    return str(item.get("door_number") or item.get("mark") or "").strip()


def _identity(item: dict[str, Any]) -> str:
    """Stable key for matching a re-extracted row to an existing line item."""
    mark = door_number(item)
    if mark:
        return f"mark:{mark}"
    return "desc:" + (item.get("description") or item.get("raw_row") or "").strip().lower()[:80]


def _status_for(item: dict[str, Any]) -> str:
    if item.get("duplicate_of") or item.get("is_duplicate"):
        return "duplicate"
    confidence = item.get("confidence")
    if item.get("flags") or (confidence is not None and confidence < CONFIDENCE_FLOOR):
        return "needs_look"
    return "clear"
