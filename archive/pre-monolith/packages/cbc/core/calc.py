"""Quote arithmetic - compatibility shim.

Pure formulas live in `cbc.domain.calc`. Live Mongo lookups live in
`cbc.services.reference_calc`. This module re-exports both so existing
`from cbc.core import calc` call sites keep working for one stage.
"""
from __future__ import annotations

from cbc.domain.calc import (  # noqa: F401
    DEFAULT_BANDS,
    DEFAULT_TAX_RATES,
    calculate_line,
    cost_from_list,
    normalise_state,
)
from cbc.services.reference_calc import (  # noqa: F401
    apply_margin,
    bands,
    compute_totals,
    invalidate_reference_caches,
    lookup_lite_kit_list_price,
    tax_rates,
    validate_margin,
)
