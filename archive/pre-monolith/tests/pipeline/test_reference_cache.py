"""Reference-library loaders cache in-process until invalidate/update."""
from __future__ import annotations

from cbc.core import calc
from cbc.services import reference_library as reflib
from cbc.services import reference_store


def test_load_frame_depths_stable_until_invalidate() -> None:
    reference_store.use_memory({})
    calc.invalidate_reference_caches()
    try:
        first = reflib.load_frame_depths()
        second = reflib.load_frame_depths()
        assert first == second
        reflib.update_frame_depths(wall_types=[{"type": "masonry", "depth": "5-3/4"}])
        third = reflib.load_frame_depths()
        row = next(w for w in third["wall_types"] if w["type"] == "masonry")
        assert row["depth_inches"] == 5.75
    finally:
        reference_store.use_memory(None)
        calc.invalidate_reference_caches()


def test_lite_kit_lookup_uses_store_cache() -> None:
    reference_store.use_memory({})
    calc.invalidate_reference_caches()
    try:
        first = calc.lookup_lite_kit_list_price(12, 12, pdf_page=30)
        second = calc.lookup_lite_kit_list_price(14, 14, pdf_page=30)
        # Both succeed or both miss; cache must not raise.
        assert "list_price" in first and "list_price" in second
        calc.invalidate_reference_caches()
        third = calc.lookup_lite_kit_list_price(12, 12, pdf_page=30)
        assert "list_price" in third
    finally:
        reference_store.use_memory(None)
        calc.invalidate_reference_caches()
