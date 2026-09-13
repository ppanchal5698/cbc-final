#!/usr/bin/env python3
"""reference MCP server — read curated pricing knowledge from Mongo.

JSON under reference-library/ is seed only. Live values come from referenceData.
READ-ONLY: no write tools; prefer MONGODB_READONLY_URI when set.
"""
from __future__ import annotations

from typing import Any

from _runtime import serve
from tools import TOOLS

from cbc.core.calc import lookup_lite_kit_list_price
from cbc.modules.pricing.api import reference_library as reflib
from cbc.modules.pricing.api import reference_store


def list_reference_families() -> dict[str, Any]:
    return {"families": reference_store.list_families_sync()}


def get_reference_document(family: str) -> dict[str, Any]:
    try:
        data = reference_store.get_family_sync(family, prefer_ro=True)
    except KeyError as exc:
        return {"error": str(exc), "family": family}
    return {"family": family, "data": data}


def get_margin_bands() -> dict[str, Any]:
    return reflib.load_margins()


def get_tax_rates() -> dict[str, Any]:
    return reflib.load_tax_rates()


def get_finish_crosswalk() -> dict[str, Any]:
    return reflib.load_finishes()


def get_frame_depth(wall_type: str) -> dict[str, Any]:
    hit = reflib.depth_for_wall_type(wall_type)
    if hit is None:
        return {"wall_type": wall_type, "depth": None, "note": "No match in frame_depths."}
    return hit


def get_frp_constants() -> dict[str, Any]:
    return reflib.load_frp_constants()


def get_manual_adders() -> dict[str, Any]:
    return reflib.load_adders()


def get_special_customer_margin(customer: str) -> dict[str, Any]:
    hit = reflib.get_special_customer_margin(customer)
    if hit is None:
        return {"customer": customer, "margin": None, "note": "No special margin on file."}
    return hit


def get_vendor_tier(vendor: str, category: str | None = None) -> dict[str, Any]:
    return reflib.get_vendor_tier(vendor, category)


def get_special_net(vendor: str, part: str) -> dict[str, Any] | None:
    return reflib.get_special_net(vendor, part)


def lookup_lite_kit(
    width_in: float,
    height_in: float,
    pdf_page: int | None = None,
) -> dict[str, Any]:
    return lookup_lite_kit_list_price(width_in, height_in, pdf_page)


def is_stock_item(vendor: str, part: str) -> dict[str, Any]:
    return reflib.is_stock_part(vendor, part)


def get_custom_other_matrix() -> dict[str, Any]:
    return reflib.load_custom_other_matrix()


HANDLERS = {
    "list_reference_families": list_reference_families,
    "get_reference_document": get_reference_document,
    "get_margin_bands": get_margin_bands,
    "get_tax_rates": get_tax_rates,
    "get_finish_crosswalk": get_finish_crosswalk,
    "get_frame_depth": get_frame_depth,
    "get_frp_constants": get_frp_constants,
    "get_manual_adders": get_manual_adders,
    "get_special_customer_margin": get_special_customer_margin,
    "get_vendor_tier": get_vendor_tier,
    "get_special_net": get_special_net,
    "lookup_lite_kit": lookup_lite_kit,
    "is_stock_item": is_stock_item,
    "get_custom_other_matrix": get_custom_other_matrix,
}

_FORBIDDEN = ("write", "update", "insert", "upsert", "delete", "create", "set_", "put_")
assert not [t for t in TOOLS if any(word in t["name"].lower() for word in _FORBIDDEN)], (
    "reference must expose no write tools"
)
assert set(HANDLERS) == {t["name"] for t in TOOLS}, "every tool needs a handler"


def _demo() -> None:
    """Runnable check against the live reference families.

    Seed JSON is read from REFERENCE_DIR, which defaults to a repo-root
    `reference-library/` that exists only inside the image - the checkout keeps
    it at `data/reference-library`. Skip on a missing seed the way the catalog
    demo skips a missing index, so CI reports an absent path rather than a
    failing rule.
    """
    try:
        families = list_reference_families()["families"]
        assert "margins" in families and "vendor_tiers" in families
        bands = get_margin_bands()
        assert bands.get("bands"), bands
        assert get_vendor_tier("acme")["multiplier"] is None
    except FileNotFoundError as exc:
        print(f"reference demo SKIPPED - seed data not present: {exc.filename}")
        return
    print(f"reference demo OK - {len(families)} families")


if __name__ == "__main__":
    serve("reference", TOOLS, HANDLERS, demo=_demo)
