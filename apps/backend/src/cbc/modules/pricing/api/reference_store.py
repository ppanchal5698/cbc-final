"""Mongo-backed reference data (live source of truth).

JSON under REFERENCE_DIR / reference-library/ is seed + fixtures only. A family
CBC keeps in a file of its own form - the Division 10 cross-reference matrix - is
seeded by reading that file, so there is one copy of it to keep up to date.
Sync helpers serve calc, MCP, and workers; async helpers serve FastAPI.
"""
from __future__ import annotations

import asyncio
import json
import logging
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from cbc.shared.config import settings
from cbc.shared.mongo_uri import reachable_uri
from cbc.shared.paths import pricebook_dir

log = logging.getLogger("cbc.reference_store")

COLLECTION = "referenceData"

# family id -> path relative to REFERENCE_DIR
SEED_FILES: dict[str, str] = {
    "margins": "margins/margin_framework.json",
    "tax": "tax/sales_tax_rates.json",
    "manual_adders": "adders/manual_adders.json",
    "lite_kit_prices": "adders/lite_kit_prices.json",
    "vendor_tiers": "multipliers/vendor_tiers.json",
    "hager_special_nets": "multipliers/hager_special_nets.json",
    "special_customer_margins": "multipliers/special_customer_margins.json",
    "finishes": "finishes/finish_crosswalk.json",
    "frame_depths": "frame_depths/wall_type_to_depth.json",
    "frp_constants": "frp_constants/conversion_constants.json",
    "hager_top10_stock": "hardware_sets/hager_top10_stock.json",
    "allegion_stock": "hardware_sets/allegion_stock.json",
    "custom_other_matrix": "hardware_sets/custom_other_matrix.json",
}


def _div10_equals() -> dict[str, Any]:
    """Shanda's cross-reference matrix as direct equals (Matrix 6.4): a specified
    model and its equal in each brand the matrix has a column for."""
    path = pricebook_dir() / "catalogs" / "catalog_cross_reference.md"
    if not path.is_file():
        raise KeyError(f"reference family div10_equals has no data yet - {path.name} is not in the price books")
    brands: list[str] = []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [c.strip().strip("`").strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or not line.lstrip().startswith("|") or cells[0].startswith(":"):
            continue
        if not brands:  # the header names the brands: `Bobrick Equivalent` -> Bobrick
            brands = [c.replace("Equivalent", "").strip() for c in cells[1:]]
            continue
        values = [None if c in ("—", "-", "") else c for c in cells]
        if len(values) == len(brands) + 1 and any(values):
            rows.append({"specified": values[0], **dict(zip(brands, values[1:]))})
    return {
        "description": ("Division 10 direct equals. When the part a drawing specifies cannot be priced, "
                        "the pricer offers the first brand in preferred_brands whose equal the catalog "
                        "prices, with a substitution note for the GC to approve (Matrix 6.4)."),
        "source": f"Shanda's Cross Reference Matrix - data/pricebooks/catalogs/{path.name}",
        # The matrix's own column order until CBC says which it prefers: Matrix 6.4
        # leaves it to estimator judgment.
        "preferred_brands": brands,
        # How each brand's catalog rows write a part the matrix writes bare.
        "catalog_prefixes": {"Bobrick": "B-", "ASI": "10-", "Gamco": "G-", "Bradley": ""},
        "rows": rows,
    }


# Families seeded by reading a file CBC keeps in its own form, not a JSON seed.
SEED_BUILDERS = {"div10_equals": _div10_equals}

FAMILIES: frozenset[str] = frozenset(SEED_FILES) | frozenset(SEED_BUILDERS)

# Tests can inject a dict backend: family -> {data, updatedAt, ...}
_memory: dict[str, dict[str, Any]] | None = None
# Superseded reference revisions while in memory mode (see §4.6 below).
_memory_revisions: dict[str, list[dict[str, Any]]] = {}
_cache: dict[str, tuple[Any, dict[str, Any]]] = {}
_sync_client: MongoClient | None = None
_ro_client: MongoClient | None = None


def use_memory(store: dict[str, dict[str, Any]] | None) -> None:
    """Test helper — None restores Mongo/seed path.

    The in-memory revision history is reset with it. Leaving it behind made one
    test's superseded margin bands turn up as another's history.
    """
    global _memory
    _memory = store
    _cache.clear()
    _memory_revisions.clear()


def invalidate(family: str | None = None) -> None:
    if family is None:
        _cache.clear()
    else:
        _cache.pop(family, None)


def seed_root() -> Path:
    return Path(settings.reference_dir)


def _seed_path(family: str) -> Path:
    rel = SEED_FILES.get(family)
    if not rel:
        raise KeyError(f"unknown reference family: {family}")
    return seed_root() / rel


def load_seed_json(family: str) -> dict[str, Any]:
    if family in SEED_BUILDERS:
        return SEED_BUILDERS[family]()
    path = _seed_path(family)
    if not path.is_file():
        # A family whose seed is not in the reference library yet holds nothing:
        # the same answer as a family nobody has stored.
        raise KeyError(f"reference family {family} has no data yet - {path.name} is not in the library")
    return json.loads(path.read_text(encoding="utf-8"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _doc(family: str, data: dict[str, Any], *, actor: str | None = None) -> dict[str, Any]:
    return {
        "_id": family,
        "family": family,
        "schemaVersion": 1,
        "updatedAt": _now(),
        "updatedBy": actor,
        "data": data,
    }


def _sync_collection() -> Collection | None:
    """Writable sync collection, or None if Mongo is unreachable."""
    global _sync_client
    if _memory is not None:
        return None
    uri = reachable_uri(settings.mongodb_uri)
    try:
        if _sync_client is None:
            _sync_client = MongoClient(
                uri,
                tz_aware=True,
                serverSelectionTimeoutMS=3000,
                connectTimeoutMS=3000,
            )
            _sync_client.admin.command("ping")
        return _sync_client[settings.mongodb_db][COLLECTION]
    except Exception as exc:
        log.warning("reference_store sync Mongo unavailable: %s", exc)
        _sync_client = None
        return None


def _ro_sync_collection() -> Collection | None:
    """Prefer the read-only URI for MCP; fall back to the primary.

    The client is kept, like `_sync_client`. Building and pinging a new one on every
    call was a connection handshake per reference lookup.
    """
    global _ro_client
    if _memory is not None:
        return None
    from cbc.shared.mongo import readonly_uri

    try:
        if _ro_client is None:
            _ro_client = MongoClient(
                reachable_uri(readonly_uri() or settings.mongodb_uri),
                tz_aware=True,
                serverSelectionTimeoutMS=3000,
                connectTimeoutMS=3000,
            )
            _ro_client.admin.command("ping")
        return _ro_client[settings.mongodb_db][COLLECTION]
    except Exception as exc:
        log.warning("reference_store RO Mongo unavailable: %s", exc)
        _ro_client = None
        return _sync_collection()


def get_family_sync(family: str, *, prefer_ro: bool = False) -> dict[str, Any]:
    """Return a deep copy of the family's `data` blob."""
    if family not in FAMILIES:
        raise KeyError(f"unknown reference family: {family}")

    if _memory is not None:
        row = _memory.get(family)
        if row:
            return deepcopy(row["data"])
        data = load_seed_json(family)
        _memory[family] = _doc(family, data)
        return deepcopy(data)

    cached = _cache.get(family)
    coll = _ro_sync_collection() if prefer_ro else _sync_collection()
    if coll is not None:
        try:
            row = coll.find_one({"_id": family})
            if row and isinstance(row.get("data"), dict):
                stamp = row.get("updatedAt")
                if cached and cached[0] == stamp:
                    return deepcopy(cached[1])
                data = deepcopy(row["data"])
                _cache[family] = (stamp, data)
                return deepcopy(data)
        except PyMongoError as exc:
            log.warning("reference get %s failed: %s", family, exc)

    # Seed fallback when Mongo empty/down (dev + first boot before seed).
    data = load_seed_json(family)
    _cache[family] = (None, data)
    return deepcopy(data)


def family_stamp_sync(family: str) -> dict[str, Any] | None:
    """When the family last changed and who changed it - None while it is still
    the seed nobody has saved."""
    if family not in FAMILIES:
        raise KeyError(f"unknown reference family: {family}")
    if _memory is not None:
        row = _memory.get(family)
    else:
        coll = _sync_collection()
        try:
            row = coll.find_one({"_id": family}, {"updatedAt": 1, "updatedBy": 1}) if coll is not None else None
        except PyMongoError as exc:
            log.warning("reference stamp %s failed: %s", family, exc)
            row = None
    if not row or not row.get("updatedAt"):
        return None
    return {"updatedAt": row["updatedAt"], "updatedBy": row.get("updatedBy")}


def put_family_sync(
    family: str,
    data: dict[str, Any],
    *,
    actor: str | None = None,
) -> dict[str, Any]:
    """Replace family data; return the stored `data` copy."""
    if family not in FAMILIES:
        raise KeyError(f"unknown reference family: {family}")
    payload = deepcopy(data)
    doc = _doc(family, payload, actor=actor)

    if _memory is not None:
        previous = _memory.get(family)
        if previous is not None:
            _archive(previous, superseded_by=actor, at=doc["updatedAt"])
        _memory[family] = doc
        invalidate(family)
        return deepcopy(payload)

    coll = _sync_collection()
    if coll is None:
        raise RuntimeError("MongoDB is required to persist reference data")
    previous = coll.find_one({"_id": family})
    if previous is not None:
        _archive(previous, superseded_by=actor, at=doc["updatedAt"])
    coll.replace_one({"_id": family}, doc, upsert=True)
    invalidate(family)
    return deepcopy(payload)


# ── §4.6: reference data is versioned, never overwritten ────────────────────
#
# `replace_one` destroyed the previous document outright, so editing a margin
# band or a tax rate erased the answer to "what was the rate when we quoted
# this?" - the question NFR-3 exists to make answerable, and the reason §4.6
# names nine collections that must be "versioned by effective date, never
# updated in place". Price changes arrive as dated memos with a protection
# window (Matrix 6.3); an in-place update cannot represent that.
#
# The superseded revision is archived beside the live document rather than
# replacing the read path, so `load()` stays a single lookup and history
# accumulates where an auditor can reach it.
REVISIONS = "referenceDataRevisions"



def _archive(previous: dict[str, Any], *, superseded_by: str | None, at: Any) -> None:
    family = previous.get("family") or previous.get("_id")
    revision = {
        "family": family,
        "data": deepcopy(previous.get("data")),
        "effectiveFrom": previous.get("effectiveFrom") or previous.get("updatedAt"),
        "effectiveTo": at,
        "writtenBy": previous.get("updatedBy"),
        "supersededBy": superseded_by,
    }
    if _memory is not None:
        _memory_revisions.setdefault(family, []).append(revision)
        return
    coll = _sync_collection()
    if coll is not None:
        coll.database[REVISIONS].insert_one(revision)


def revisions(family: str) -> list[dict[str, Any]]:
    """Every superseded revision of a family, oldest first.

    The live document is not a revision - it is what `load()` returns.
    """
    if family not in FAMILIES:
        raise KeyError(f"unknown reference family: {family}")
    if _memory is not None:
        return [deepcopy(r) for r in _memory_revisions.get(family, [])]
    coll = _sync_collection()
    if coll is None:
        return []
    return list(coll.database[REVISIONS].find({"family": family}).sort("effectiveTo", 1))


def as_of(family: str, when: Any) -> dict[str, Any] | None:
    """The `data` that was in force at a moment, or None if nothing was.

    This is the NFR-3 question asked directly: what was the multiplier tier, the
    tax rate, the margin band when this line was quoted?
    """
    for revision in revisions(family):
        frm, to = revision.get("effectiveFrom"), revision.get("effectiveTo")
        if (frm is None or frm <= when) and (to is None or when <= to):
            return deepcopy(revision["data"])
    return get_family_sync(family)


def list_families_sync() -> list[str]:
    return sorted(FAMILIES)


async def get_family(family: str) -> dict[str, Any]:
    from cbc.modules.pricing.infrastructure.collections import reference_data

    if family not in FAMILIES:
        raise KeyError(f"unknown reference family: {family}")
    if _memory is not None:
        return get_family_sync(family)
    row = await reference_data().find_one({"_id": family})
    if row and isinstance(row.get("data"), dict):
        return deepcopy(row["data"])
    return get_family_sync(family)


async def put_family(
    family: str,
    data: dict[str, Any],
    *,
    actor: str | None = None,
) -> dict[str, Any]:
    from cbc.modules.pricing.infrastructure.collections import reference_data

    if family not in FAMILIES:
        raise KeyError(f"unknown reference family: {family}")
    if _memory is not None:
        return put_family_sync(family, data, actor=actor)
    payload = deepcopy(data)
    doc = _doc(family, payload, actor=actor)
    previous = await reference_data().find_one({"_id": family})
    if previous is not None:
        await asyncio.to_thread(_archive, previous, superseded_by=actor, at=doc["updatedAt"])
    await reference_data().replace_one({"_id": family}, doc, upsert=True)
    invalidate(family)
    return deepcopy(payload)


async def ensure_reference_seed(*, force: bool = False) -> list[str]:
    """Insert missing families from JSON seed. Never overwrite unless force."""
    from cbc.modules.pricing.infrastructure.collections import reference_data

    seeded: list[str] = []
    for family in sorted(FAMILIES):
        try:
            data = load_seed_json(family)
        except KeyError as exc:
            log.warning("reference seed missing: %s", exc)
            continue
        if _memory is not None:
            if force or family not in _memory:
                put_family_sync(family, data, actor="seed")
                seeded.append(family)
            continue
        existing = await reference_data().find_one({"_id": family}, {"_id": 1})
        if existing and not force:
            continue
        await put_family(family, data, actor="seed")
        seeded.append(family)
    if seeded:
        log.info("reference seed wrote %s families: %s", len(seeded), ", ".join(seeded))
    return seeded
