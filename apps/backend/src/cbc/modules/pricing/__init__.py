"""pricing: pricing policy - margins, tax, adders, tiers, nets, finishes, frame depths, FRP.

It owns `referenceData` and `referenceDataRevisions`: the curated reference
library, seeded from REFERENCE_DIR and versioned on every edit. Other modules,
the kernel's calc and the MCP servers read it through `cbc.modules.pricing.api`.
"""
from __future__ import annotations


def register(app) -> None:
    """Mount this module's routes on the application."""
    from cbc.modules.pricing.features import (
        Adders,
        CustomOtherMatrix,
        DeleteEntry,
        Finishes,
        FrameDepths,
        FrpConstants,
        LiteKit,
        Margins,
        SpecialMargins,
        SpecialNets,
        Stock,
        Tax,
        VendorTiers,
    )

    # DeleteEntry is a pattern over every family; it goes after the named paths.
    for feature in (
        Margins,
        Tax,
        Adders,
        SpecialMargins,
        Finishes,
        FrameDepths,
        FrpConstants,
        VendorTiers,
        SpecialNets,
        LiteKit,
        Stock,
        CustomOtherMatrix,
        DeleteEntry,
    ):
        app.include_router(feature.router)


async def ensure_indexes() -> None:
    from cbc.modules.pricing.infrastructure.collections import ensure_indexes as build

    await build()
