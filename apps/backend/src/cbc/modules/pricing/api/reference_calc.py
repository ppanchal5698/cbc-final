"""Live margin / tax / lite-kit lookups used by the arithmetic.

The pure formulas live in `cbc.modules.pricing.domain.calc`. This module is the I/O half: Mongo
(via reference_library) with DEFAULT_* fallbacks.
"""
from __future__ import annotations

from typing import Any

from cbc.modules.pricing.domain import calc as rules
from cbc.modules.pricing.domain.calc import DEFAULT_BANDS, DEFAULT_TAX_RATES

_bands_cache: tuple[Any, dict[str, float]] | None = None
_tax_cache: tuple[Any, dict[str, float]] | None = None
_lite_kit_cache: dict[str, Any] | None = None


def invalidate_reference_caches() -> None:
    """Call after Admin updates margins/tax/lite-kit in Mongo."""
    global _bands_cache, _tax_cache, _lite_kit_cache
    _bands_cache = None
    _tax_cache = None
    _lite_kit_cache = None
    from cbc.modules.pricing.api import reference_store

    reference_store.invalidate("margins")
    reference_store.invalidate("tax")
    reference_store.invalidate("lite_kit_prices")


def bands() -> dict[str, float]:
    """The margin bands from Mongo (seed JSON fallback)."""
    global _bands_cache
    from cbc.modules.pricing.api import reference_library as reflib

    try:
        data = reflib.load_margins()
    except Exception:
        return dict(DEFAULT_BANDS)
    stamp = tuple(
        (b.get("key"), b.get("margin")) for b in data.get("bands", []) if b.get("key")
    ) + (("accessories", data.get("accessories_derived")),)
    if _bands_cache and _bands_cache[0] == stamp:
        return dict(_bands_cache[1])
    bands_map = {b["key"]: float(b["margin"]) for b in data.get("bands", []) if "key" in b}
    if "accessories_derived" in data and data["accessories_derived"] is not None:
        bands_map["accessories"] = float(data["accessories_derived"])
    result = bands_map or dict(DEFAULT_BANDS)
    _bands_cache = (stamp, result)
    return dict(result)


def tax_rates() -> dict[str, float]:
    """Nexus tax rates from Mongo (seed JSON fallback)."""
    global _tax_cache
    from cbc.modules.pricing.api import reference_library as reflib

    try:
        data = reflib.load_tax_rates()
    except Exception:
        return dict(DEFAULT_TAX_RATES)
    if "rates" not in data:
        return dict(DEFAULT_TAX_RATES)
    result = {str(code).upper(): float(rate) for code, rate in (data["rates"] or {}).items()}
    stamp = tuple(sorted(result.items()))
    if _tax_cache and _tax_cache[0] == stamp:
        return dict(_tax_cache[1])
    _tax_cache = (stamp, result)
    return dict(result)


def _lite_kit_data() -> dict[str, Any] | None:
    global _lite_kit_cache
    if _lite_kit_cache is not None:
        return _lite_kit_cache
    from cbc.modules.pricing.api import reference_library as reflib

    try:
        _lite_kit_cache = reflib.load_lite_kit_prices()
    except Exception:
        return None
    return _lite_kit_cache


def lookup_lite_kit_list_price(
    width_in: float,
    height_in: float,
    pdf_page: int | None = None,
) -> dict[str, Any]:
    return rules.lookup_lite_kit_list_price_from_data(
        _lite_kit_data(), width_in, height_in, pdf_page=pdf_page
    )


def apply_margin(
    cost: float,
    product_type: str,
    override_margin: float | None = None,
    override_reason: str | None = None,
) -> dict[str, Any]:
    return rules.apply_margin(
        cost,
        product_type,
        override_margin=override_margin,
        override_reason=override_reason,
        bands_map=bands(),
    )


def validate_margin(product_type: str, applied_margin: float) -> dict[str, Any]:
    return rules.validate_margin(product_type, applied_margin, bands_map=bands())


def compute_totals(
    line_items: list[dict[str, Any]], project_state: str | None = None
) -> dict[str, Any]:
    return rules.compute_totals(line_items, project_state, tax_map=tax_rates())
