"""A version's differences from the bid as it stands, and an estimator's decision
on each (FR-14).

Requirements 6.4: "the copilot proposes a diff for the estimator to accept line by
line". Every door and every quote line added, removed or changed since the
version was frozen is a row, and the estimator keeps it or reverts it. A revert
puts the version's back - a changed field to its value, an addition taken out, a
removal restored. Nothing is merged on its own.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from cbc.modules.extraction.api import openings as extraction_openings
from cbc.modules.quoting.api import lines as quoting_lines
from cbc.modules.quoting.api import quote as quote_service
from cbc.shared.mongo import revive

# What a door and a quote line are compared on.
OPENING_FIELDS = ("description", "size", "qty", "hwSet", "finish", "fireRating", "handing")
LINE_FIELDS = ("description", "part", "qty", "cost", "margin", "alternateGroup")
_LIVE_ONLY = ("projectId", "estimateVersionId")


def opening_key(item: dict[str, Any]) -> str:
    return str(item.get("mark") or item.get("description", ""))[:60]


def line_key(item: dict[str, Any]) -> str:
    return str(item.get("lineKey") or item.get("id") or item.get("_id"))


async def _state(project: dict[str, Any], stored: dict[str, Any]) -> dict[str, tuple[dict, dict]]:
    """Per kind: the version's rows and the live ones, by key."""
    live_openings = await extraction_openings.list_for_project(project["_id"], limit=5000)
    live_lines = await quoting_lines.list_for_project(project["_id"])
    return {
        "opening": ({opening_key(i): i for i in stored["snapshot"]["lineItems"]},
                    {opening_key(i): i for i in live_openings}),
        "line": ({line_key(i): i for i in stored["snapshot"].get("quoteLines") or []},
                 {line_key(i): i for i in live_lines}),
    }


def _fields(kind: str) -> tuple[str, ...]:
    return OPENING_FIELDS if kind == "opening" else LINE_FIELDS


def _differing(kind: str, was: dict[str, Any], now: dict[str, Any]) -> list[str]:
    return [f for f in _fields(kind) if str(was.get(f)) != str(now.get(f))]


def _label(kind: str, item: dict[str, Any]) -> str | None:
    if kind == "opening":
        return item.get("mark") or item.get("description")
    return item.get("description") or item.get("part")


async def rows(project: dict[str, Any], stored: dict[str, Any]) -> list[dict[str, Any]]:
    """Every difference, door and quote line alike, with the decision recorded on it."""
    decided = decisions(stored)
    out: list[dict[str, Any]] = []
    for kind, (before, live) in (await _state(project, stored)).items():
        for key in sorted(set(before) | set(live)):
            was, now = before.get(key), live.get(key)
            if was is not None and now is not None:
                fields = _differing(kind, was, now)
                if not fields:
                    continue
                row = {"change": "changed", "fields": fields,
                       "before": {f: was.get(f) for f in fields}, "after": {f: now.get(f) for f in fields}}
            else:
                row = {"change": "added" if now is not None else "removed"}
            out.append({"kind": kind, "key": key, "label": _label(kind, now or was), **row,
                        "decision": decided.get(f"{kind}:{key}")})
    return out


def decisions(stored: dict[str, Any]) -> dict[str, str]:
    """The last decision on each difference, by `kind:key`."""
    return {f"{d['kind']}:{d['key']}": d["decision"] for d in stored.get("decisions") or []}


def undecided(found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The differences still standing that nobody kept - a reverted one is gone."""
    return [row for row in found if row["decision"] != "keep"]


def _restorable(doc: dict[str, Any]) -> dict[str, Any]:
    return revive({key: value for key, value in doc.items() if key not in _LIVE_ONLY})


async def revert(project: dict[str, Any], stored: dict[str, Any], kind: str, key: str, actor: str) -> bool:
    """Put the version's back for one difference. False when there is none."""
    before, live = (await _state(project, stored))[kind]
    was, now = before.get(key), live.get(key)
    reason = f"reverted to version {stored['version']}"
    if kind == "opening":
        if was is not None and now is not None:
            fields = {f: was.get(f) for f in _differing(kind, was, now)}
            if not fields:
                return False
            await extraction_openings.update_fields(
                now["_id"], {**fields, "updatedAt": datetime.now(timezone.utc)})
        elif now is not None:
            await extraction_openings.remove(project["_id"], [now["_id"]])
        elif was is not None:
            await extraction_openings.restore(project["_id"], _restorable(was))
        else:
            return False
        return True

    if was is not None and now is not None:
        fields = {f: was.get(f) for f in _differing(kind, was, now)}
        if not fields:
            return False
        await quoting_lines.set_fields(project["_id"], key, fields, by=actor, reason=reason)
    elif now is not None:
        await quoting_lines.delete_by_key(project["_id"], key)
    elif was is not None:
        await quoting_lines.restore(project["_id"], _restorable(was))
    else:
        return False
    await quote_service.persist(project)
    return True
