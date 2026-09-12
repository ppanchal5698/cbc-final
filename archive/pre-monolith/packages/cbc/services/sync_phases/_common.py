"""Shape-handling shared by the phase modules.

A pass writes a bare array one run and a `{"openings": [...]}` wrapper the
next, so reading one of these files is its own small problem and every phase
has it. Kept together rather than duplicated per module.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("cbc.services.sync")

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read_json(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _lines_in(payload: dict[str, Any] | list[Any], filename: str, key: str) -> list[Any]:
    """The records in a priced artifact, whether or not they came wrapped.

    A run is asked for `{"lines": [...]}` and writes a bare array about as often.
    The door-schedule path has accepted both since early on; the priced path did
    not, so a full pipeline that had completed all six phases and written a whole
    quote failed on `'list' object has no attribute 'get'` at the very last step.

    The wrapper carries nothing the records do not - taking either shape loses no
    information and no check: every line still goes through validation.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload.get(key, [])
    raise ValueError(f"{filename} must be a JSON object or an array")


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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


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


def _distinct_keys(items: list[dict[str, Any]], identity) -> list[str]:
    """Per-row keys, unique within one payload.

    A schedule really can list the same mark twice, and the plain identity made
    every repeat collide: the lookup built before the loop held one of them, so
    both rows saw "no match" and both inserted - fresh duplicates on every run,
    with the older copy orphaned and never updated again. Numbering the repeats
    keeps each row matched to its own record, and keeps that stable across runs
    because the schedule order is stable.
    """
    seen: dict[str, int] = {}
    keys = []
    for item in items:
        base = identity(item)
        seen[base] = seen.get(base, 0) + 1
        keys.append(base if seen[base] == 1 else f"{base}#{seen[base]}")
    return keys


def _status_for(item: dict[str, Any]) -> str:
    if item.get("duplicate_of") or item.get("is_duplicate"):
        return "duplicate"
    confidence = item.get("confidence")
    if item.get("flags") or (confidence is not None and confidence < 0.75):
        return "needs_look"
    return "clear"


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
