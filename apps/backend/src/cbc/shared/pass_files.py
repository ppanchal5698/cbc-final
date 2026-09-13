"""Reading back the JSON a Claude pass writes, writing it down, and keying its rows.

Extraction's door schedule and quoting's priced lines both have all three
problems, so the answers live here once rather than in each module.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def distinct_keys(items: list[dict[str, Any]], identity) -> list[str]:
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
