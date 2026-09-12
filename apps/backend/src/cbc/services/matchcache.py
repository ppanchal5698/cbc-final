"""Project-scoped product-match cache (audit C-08 / NFR-2).

A re-price used to re-decide every match. High-confidence decisions that nothing
invalidated are reused; anything below 0.75 is never stored or served — a flagged
match must not become a settled fact.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cbc.core.paths import repo_root
from cbc.services import manifests

ROOT = repo_root()
PROJECTS = ROOT / "projects"
MATCHCACHE_REL = "extracted/_matchcache.json"
HARDWARE_SETS_REL = "extracted/hardware_sets.json"
DOOR_SCHEDULE_REL = "extracted/door_schedule.json"
JOB_TYPES = frozenset({"match_and_price", "run_full_pipeline"})
CONFIDENCE_FLOOR = 0.75
# Bump when product-matcher or match-hardware-sets changes how a match is decided.
MATCHER_PROMPT_VERSION = "1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cache_path(slug: str) -> Path:
    return PROJECTS / slug / MATCHCACHE_REL


def catalog_watermark() -> str:
    """max(builtAt) across pageIndex; empty when the collection is unreachable."""
    try:
        from cbc.db import database

        rows = list(database()["pageIndex"].find({}, {"builtAt": 1}).limit(200))
    except Exception:
        return ""
    if not rows:
        return ""
    return max(str(row.get("builtAt") or "") for row in rows)


def item_key(specified: Any, watermark: str) -> str:
    blob = json.dumps(
        {
            "specified": specified,
            "watermark": watermark,
            "version": MATCHER_PROMPT_VERSION,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _iter_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    found: list[dict[str, Any]] = []
    for group in payload.get("groups") or []:
        if not isinstance(group, dict):
            continue
        for item in group.get("items") or []:
            if isinstance(item, dict):
                found.append(item)
    for item in payload.get("items") or []:
        if isinstance(item, dict):
            found.append(item)
    return found


def _confidence(item: dict[str, Any]) -> float:
    try:
        return float(item.get("confidence"))
    except (TypeError, ValueError):
        return 0.0


def ingest(slug: str) -> dict[str, Any]:
    """Write high-confidence matches from hardware_sets.json into the cache."""
    root = PROJECTS / slug
    live = root / HARDWARE_SETS_REL
    payload_out: dict[str, Any] = {
        "generated_at": _now(),
        "matcherPromptVersion": MATCHER_PROMPT_VERSION,
        "catalogWatermark": catalog_watermark(),
        "doorScheduleSha256": _sha256_file(root / DOOR_SCHEDULE_REL),
        "entries": [],
    }
    if not live.is_file():
        return payload_out
    sidecar = manifests.sidecar_path(slug, HARDWARE_SETS_REL)
    if sidecar.is_file() and not manifests.reuse_ok(slug, HARDWARE_SETS_REL):
        if cache_path(slug).is_file():
            try:
                return json.loads(cache_path(slug).read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        return payload_out
    try:
        hardware = json.loads(live.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return payload_out

    watermark = payload_out["catalogWatermark"]
    door_sha = payload_out["doorScheduleSha256"]
    entries: list[dict[str, Any]] = []
    for item in _iter_items(hardware):
        confidence = _confidence(item)
        if confidence < CONFIDENCE_FLOOR:
            continue
        specified = item.get("specified")
        if specified is None:
            continue
        entries.append(
            {
                "key": item_key(specified, watermark),
                "specified": specified,
                "matched": item.get("matched"),
                "confidence": confidence,
                "match_tier": item.get("match_tier"),
                "why": item.get("substitution_note") or item.get("why"),
                "cost_source": item.get("cost_source"),
                "flags": item.get("flags") or [],
                "dependencies": {
                    "doorScheduleSha256": door_sha,
                    "catalogWatermark": watermark,
                    "matcherPromptVersion": MATCHER_PROMPT_VERSION,
                },
            }
        )
    payload_out["entries"] = entries
    target = cache_path(slug)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload_out, indent=2), encoding="utf-8")
    return payload_out


def reusable(slug: str, *, force: bool = False) -> list[dict[str, Any]]:
    """Entries whose dependency hashes still match. Empty on force or miss."""
    if force:
        return []
    path = cache_path(slug)
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if str(payload.get("matcherPromptVersion") or "") != MATCHER_PROMPT_VERSION:
        return []
    watermark = catalog_watermark()
    door_sha = _sha256_file(PROJECTS / slug / DOOR_SCHEDULE_REL)
    kept: list[dict[str, Any]] = []
    for entry in payload.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        if float(entry.get("confidence") or 0) < CONFIDENCE_FLOOR:
            continue
        deps = entry.get("dependencies") or {}
        if deps.get("catalogWatermark") != watermark:
            continue
        if deps.get("doorScheduleSha256") != door_sha:
            continue
        if deps.get("matcherPromptVersion") != MATCHER_PROMPT_VERSION:
            continue
        kept.append(entry)
    return kept


def prompt_block(entries: list[dict[str, Any]] | None) -> str:
    if not entries:
        return ""
    lines = [
        "**Reuse these cached matches** (confidence ≥ 0.75, dependencies unchanged).",
        "Copy them into `extracted/hardware_sets.json` as-is. Rematch only items",
        "that are not listed here. Do not re-decide a cached match.",
        "",
        "```json",
        json.dumps(
            [
                {
                    "specified": row.get("specified"),
                    "matched": row.get("matched"),
                    "confidence": row.get("confidence"),
                    "match_tier": row.get("match_tier"),
                    "cost_source": row.get("cost_source"),
                }
                for row in entries
            ],
            indent=2,
        ),
        "```",
        "",
    ]
    return "\n".join(lines)
