"""Is an indexed price a list price or a net price?

The index stores one `price` column and says nothing about what it means. The
catalog screen filled that gap by assuming: every indexed price was rendered as
"list $X". For a Hager special net read off the multiplier sheet that is exactly
backwards - 3.23 is already the cost, and an estimator who reads it as list and
applies the 0.21 category multiplier prices the line at 68 cents.

The distinction is a property of the sheet, not the part, and both signals it
needs are already curated:

  - `pricebooks/index.json` marks a sheet `multiplier_sheet` or `price_book`.
  - Mongo `referenceData/vendor_tiers` (seeded from vendor_tiers.json) carries
    the multiplier, and records `null` for vendors CBC buys on a flat net program.

A price is a *list* price only when there is a multiplier to apply to it. Where
neither signal resolves, this says UNKNOWN rather than picking one - the same rule
the rest of the pricing path follows, where an unknown tier returns null with a
note instead of a guess (.claude/rules/accuracy-trust.md).

This decides how a number is *labelled*. It does not decide how a line is priced:
`lookup_pricing` already consults the special-net sheet first and reports
`cost_source`, and a vendor with no multiplier cannot reach `list x multiplier` at
all, so a net has never been silently discounted a second time.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from cbc.shared.paths import repo_root

LIST = "list"
NET = "net"
UNKNOWN = "unknown"

LABELS = {
    LIST: "list price - multiply by the vendor tier to reach cost",
    NET: "net price - this is already the cost, do not apply a multiplier",
    UNKNOWN: "basis not recorded for this sheet - confirm before quoting",
}


def _file_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return (stat.st_mtime_ns, stat.st_size)


def _pricebook_dir() -> Path:
    raw = os.environ.get("PRICEBOOK_DIR")
    if not raw:
        return repo_root() / "pricebooks"
    path = Path(raw)
    return path if path.is_absolute() else (repo_root() / path).resolve()


@lru_cache(maxsize=4)
def _sheet_kinds_at(_signature: tuple[int, int]) -> dict[str, str]:
    """file name -> 'price_book' | 'multiplier_sheet', from the curated inventory."""
    index = _pricebook_dir() / "index.json"
    if not index.exists():
        return {}
    try:
        payload = json.loads(index.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        str(entry.get("file", "")): str(entry.get("kind", ""))
        for entry in payload.get("pricebooks", [])
        if entry.get("file")
    }


def _sheet_kinds() -> dict[str, str]:
    index = _pricebook_dir() / "index.json"
    if not index.exists():
        return {}
    try:
        signature = _file_signature(index)
    except OSError:
        return {}
    return dict(_sheet_kinds_at(signature))


def _vendor_tiers_payload() -> dict[str, Any]:
    from cbc.modules.pricing.api.reference_library import load_vendor_tiers

    try:
        return load_vendor_tiers()
    except Exception:
        return {}


def _vendors_with_a_multiplier() -> frozenset[str]:
    """Vendor keys whose sheets are list-priced, i.e. a multiplier exists to apply."""
    payload = _vendor_tiers_payload()
    keys = set()
    for record in payload.get("vendors", []):
        has_flat = isinstance(record.get("multiplier"), (int, float))
        has_categories = bool(record.get("categories"))
        if has_flat or has_categories:
            for name in (record.get("key"), record.get("name")):
                if name:
                    keys.add(str(name).strip().lower())
    return frozenset(keys)


def _net_program_vendors() -> frozenset[str]:
    """Vendors CBC buys on a flat net program, so their sheets carry costs already.

    Prefer an explicit `"basis": "net"` field; otherwise match curated wording.
    """
    payload = _vendor_tiers_payload()
    keys = set()
    for record in payload.get("vendors", []):
        if record.get("basis") == NET:
            stated = True
        else:
            wording = f"{record.get('tier') or ''} {record.get('note') or ''}"
            stated = "net" in wording.lower().split() or "net program" in wording.lower()
        if stated and not isinstance(record.get("multiplier"), (int, float)):
            for name in (record.get("key"), record.get("name")):
                if name:
                    keys.add(str(name).strip().lower())
    return frozenset(keys)


def price_basis(source_file: str | None, vendor: str | None) -> str:
    """LIST, NET or UNKNOWN for prices read off this sheet."""
    if _sheet_kinds().get(str(source_file or "")) == "multiplier_sheet":
        # A multiplier sheet's numbers are the special nets it exists to publish.
        return NET
    key = str(vendor or "").strip().lower()
    if key in _vendors_with_a_multiplier():
        return LIST
    if key in _net_program_vendors():
        return NET
    # No multiplier on file and no net program recorded, so nothing here can be
    # turned into a cost. An untranscribed tier looks exactly like this, which is
    # why it says so rather than picking the likelier of the two.
    return UNKNOWN


def describe(basis: str) -> str:
    return LABELS.get(basis, LABELS[UNKNOWN])


def _demo() -> None:
    """Every indexed sheet resolves, and the two that bit us resolve correctly."""
    assert price_basis("hager_multipliers.pdf", "hager") == NET
    assert price_basis("hager_price_book_18.pdf", "hager") == LIST
    assert price_basis("asi_price_list.pdf", "asi") == LIST
    # Bought on a flat net program - vendor_tiers records no multiplier and says so.
    assert price_basis("bobrick_hp_program_net.xlsx", "bobrick") == NET
    assert price_basis("gamco_hp_program_net.xlsx", "gamco") == NET
    # Pemko's tier was never transcribed; that is not the same as a net program.
    assert price_basis("pemko_markar_price_book_2026.pdf", "pemko") == UNKNOWN
    assert price_basis("nonexistent.pdf", "acme") == UNKNOWN
    assert "do not apply a multiplier" in describe(NET)
    print("cbc.modules.catalog.api.pageindex.basis OK")


if __name__ == "__main__":
    _demo()
