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

from cbc.modules.pricing.api.confidence import CONFIDENCE_FLOOR
from cbc.shared.paths import storage_root
from cbc.shared import manifests

MATCHCACHE_REL = "extracted/_matchcache.json"
HARDWARE_SETS_REL = "extracted/hardware_sets.json"
DOOR_SCHEDULE_REL = "extracted/door_schedule.json"
JOB_TYPES = frozenset(
    {
        "match_and_price",
        "run_full_pipeline",
        "extract_bid_set",
        "rerun_extraction",
    }
)
# Bump when product-matcher or match-hardware-sets changes how a match is decided.
# "2": the ladder gained Tier 0 (recall_match) and the catalog lookup normalises
# part strings, so matches decided under "1" were decided on less.
MATCHER_PROMPT_VERSION = "2"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cache_path(slug: str) -> Path:
    return storage_root() / slug / MATCHCACHE_REL


def catalog_watermark() -> str | None:
    """max(builtAt) over the indexed catalogs, or None when the index cannot be read.

    This called `list()` on an async Motor cursor, which raises; the except turned
    every call into "", so the key never moved when a price book was re-indexed and
    a cached match outlived the catalog it was made against. It now reads the page
    index through its sync read-only reader - the worker derives that credential at
    startup - with the same watermark find_pages uses. None means "cannot tell",
    and nothing is reused on it.
    """
    from cbc.modules.catalog.api.pageindex import reader
    from cbc.modules.catalog.api.pageindex.query import headers_watermark

    try:
        return headers_watermark(reader.list_catalogs())
    except Exception:
        return None


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
    root = storage_root() / slug
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
    if watermark is None:
        return []  # the catalog may have changed; a flagged-free reuse needs proof it did not
    door_sha = _sha256_file(storage_root() / slug / DOOR_SCHEDULE_REL)
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


def learning_block() -> str:
    """Tell the matcher the learned table exists, when it has anything in it.

    Not the entries themselves: recalling them needs the specification, which the
    matcher holds and this does not, and `recall_match` already answers that
    per item. This is the nudge to use the tool - silent while there is nothing
    to recall, so an empty table costs a new deployment no tokens.
    """
    from cbc.modules.catalog.api.pageindex import reader

    try:
        total = reader.learned_total()
    except Exception:
        return ""
    if not total:
        return ""
    return (
        f"**CBC has {total} specification(s) an estimator has already confirmed.**\n"
        "Call `mcp__catalog__recall_match(specified)` before matching each item. "
        "An `exact: true` recall is Tier 0 (0.97) - cite who confirmed it and when. "
        "Fire rating, handing and finish still veto it.\n\n"
    )


def prompt_block(entries: list[dict[str, Any]] | None) -> str:
    if not entries:
        return ""
    lines = [
        f"**Reuse these cached matches** (confidence ≥ {CONFIDENCE_FLOOR}, dependencies unchanged).",
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
            # Compact, not indented. This block is re-sent on every turn of the
            # pricing pass and it grows with the bid: at `indent=2` it was 185
            # characters an entry, ~11k on a 60-opening bid and ~37k on a
            # 200-line one. The separators carry no meaning to the model, and
            # every tool result it already reads is compacted the same way by
            # `_runtime.dump_payload`.
            #
            # Deliberately *not* capped. A capped entry is one the matcher has
            # to decide again, which costs more than the ~46 tokens the cached
            # row occupies - the block is the saving, not the overhead.
            separators=(",", ":"),
        ),
        "```",
        "",
    ]
    return "\n".join(lines)
