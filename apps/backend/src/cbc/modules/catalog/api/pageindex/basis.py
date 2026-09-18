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
from functools import lru_cache
from pathlib import Path
from typing import Any

from cbc.shared.paths import pricebook_dir

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
    return pricebook_dir()


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
    """Vendor keys whose sheets are list-priced, i.e. a multiplier exists to apply.

    A multiplier of exactly 1.0 is not one. It is how the tier sheet writes a flat
    net program - Bobrick reads "Priced from 2020 Distributor Net Price List
    (x1.000). Not list x discount." Treating that as list-priced sent a net sheet
    down the list x multiplier path, so changing the book's multiplier to 0.25
    repriced a $40.00 net part to $10.00.
    """
    payload = _vendor_tiers_payload()
    keys = set()
    for record in payload.get("vendors", []):
        multiplier = record.get("multiplier")
        has_flat = isinstance(multiplier, (int, float)) and not _is_identity(multiplier)
        has_categories = bool(record.get("categories"))
        if has_flat or has_categories:
            for name in (record.get("key"), record.get("name")):
                if name:
                    keys.add(str(name).strip().lower())
    return frozenset(keys)


def _is_identity(multiplier: float) -> bool:
    """x1.000 - the sheet is already the cost, whatever column it is printed in."""
    return abs(float(multiplier) - 1.0) < 1e-9


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
        multiplier = record.get("multiplier")
        # No multiplier at all, or the identity one a net program is written with.
        priced_net = not isinstance(multiplier, (int, float)) or _is_identity(multiplier)
        if stated and priced_net:
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
    # An untranscribed tier is not a net program. Pemko's categories have since
    # been transcribed, so the unit test supplies its own payload for that rule.
    assert price_basis("nonexistent.pdf", "acme") == UNKNOWN
    assert "do not apply a multiplier" in describe(NET)
    print("cbc.modules.catalog.api.pageindex.basis OK")


if __name__ == "__main__":
    _demo()
