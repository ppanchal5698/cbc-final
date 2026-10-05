"""Reference-library loaders cache in-process until invalidate/update."""
from __future__ import annotations

from cbc.modules.pricing.api import calc
from cbc.modules.pricing.api import reference_library as reflib
from cbc.modules.pricing.api import reference_store


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


def test_the_division_10_equals_are_read_from_cbcs_own_matrix(tmp_path, monkeypatch) -> None:
    """One copy of the matrix: the family is built from the markdown CBC keeps, and
    without it the family is empty rather than a crash - the memory graph walks
    every family, and the pricer asks for the equals on every bid."""
    monkeypatch.setattr(reference_store, "pricebook_dir", lambda: tmp_path)
    reference_store.use_memory({})
    try:
        assert reflib.load_div10_equals() == {}
        (tmp_path / "catalogs").mkdir()
        matrix = [
            "| Specification Model | Bobrick Equivalent | ASI Equivalent |",
            "| :--- | :--- | :--- |",
            "| `B-212` | `212` | `0714` |",
            "| `—` | `132` | `—` |",
        ]
        (tmp_path / "catalogs" / "catalog_cross_reference.md").write_text("\n".join(matrix), encoding="utf-8")
        reference_store.use_memory({})
        equals = reflib.load_div10_equals()
        assert equals["preferred_brands"] == ["Bobrick", "ASI"]
        assert equals["rows"] == [{"specified": "B-212", "Bobrick": "212", "ASI": "0714"},
                                  {"specified": None, "Bobrick": "132", "ASI": None}]
    finally:
        reference_store.use_memory(None)
