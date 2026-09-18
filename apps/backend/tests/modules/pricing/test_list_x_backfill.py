"""LIST_X backfill from Hager book for threshold / weatherstrip lines."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cbc.modules.pricing.api import hager_list_price, list_x_backfill

needs_the_book = pytest.mark.skipif(
    not Path("data/pricebooks/hager_price_book_18.pdf").exists(),
    reason="price book not present",
)


@needs_the_book
def test_lookup_785s_list_price() -> None:
    hit = hager_list_price.lookup_ngp_list_price("785S")
    assert hit is not None
    assert hit["list_price"] > 0
    assert hit["source_page"] == 531


def test_ngp_crosswalk_for_zero_188s() -> None:
    mapped = hager_list_price.ngp_for_architect_item("door_seal", "188S BK")
    assert mapped is not None
    assert mapped[0] == "785S"


@needs_the_book
def test_backfill_pemko_threshold(tmp_path, monkeypatch) -> None:
    slug = "demo_bid"
    root = tmp_path / "projects" / slug
    (root / "priced").mkdir(parents=True)
    (root / "extracted").mkdir(parents=True)

    hw = {
        "hardware_sets": [
            {
                "items": [
                    {
                        "item_type": "threshold",
                        "cost_source": "LIST_X_MULTIPLIER",
                        "multiplier": 0.4,
                        "matched": {
                            "part_number": "275A",
                            "series": '42"',
                        },
                    }
                ]
            }
        ]
    }
    (root / "extracted" / "hardware_sets.json").write_text(
        json.dumps(hw), encoding="utf-8"
    )
    priced = {
        "lines": [
            {
                "part_number": "PEMKO 275A",
                "description": "THRESHOLD",
                "quantity": 1,
                "cost": None,
                "cost_source": "MANUAL",
                "multiplier": 0.4,
                "price_book_version": "Hager Price Book #18",
            }
        ]
    }
    (root / "priced" / "line_items.json").write_text(
        json.dumps(priced), encoding="utf-8"
    )

    import cbc.shared.storage as storage_mod

    monkeypatch.setattr(storage_mod, "project_dir", lambda s: tmp_path / "projects" / s)

    stats = list_x_backfill.backfill_priced_lines(slug)
    assert stats["filled"] == 1

    updated = json.loads((root / "priced" / "line_items.json").read_text())
    line = updated["lines"][0]
    assert line["cost_source"] == "LIST_X_MULTIPLIER"
    assert line["cost"] is not None
    assert line["cost"] > 0


@needs_the_book
def test_hager_book_available_for_backfill() -> None:
    assert hager_list_price.lookup_ngp_list_price("431S") is not None


def test_hyphenated_part_maps_to_ngp() -> None:
    assert hager_list_price.ngp_for_architect_item("", "PEMKO-275A-42")[0] == "431S"
    assert hager_list_price.ngp_for_architect_item("Door Sweep / Shoe", "ZERO-39A-42")[0] == "750S"
    mapped = hager_list_price.ngp_for_architect_item(
        "Seal / Weatherstrip", "ZERO-188S-BK-18ft"
    )
    assert mapped is not None and mapped[0] == "785S"
    width = hager_list_price.parse_width_inches("Threshold, PEMKO 275A, 42 inches", "PEMKO-275A-42")
    assert width == 42
    wide = hager_list_price.ngp_for_architect_item(
        "Door Sweep / Shoe", "ZERO-39A-42", width_in=42
    )
    assert wide is not None and wide[0] == "801S"


@needs_the_book
def test_backfill_live_openings_shape_hyphenated_skus(tmp_path, monkeypatch) -> None:
    """Matcher writes openings[].items with hyphenated SKUs and no nested matched."""
    slug = "live_quote"
    root = tmp_path / "projects" / slug
    (root / "priced").mkdir(parents=True)
    (root / "extracted").mkdir(parents=True)

    hw = {
        "openings": [
            {
                "mark": "01",
                "items": [
                    {
                        "category": "Threshold",
                        "specified": 'PEMKO 275A, 42"',
                        "part_number": "PEMKO-275A-42",
                        "cost_source": "LIST_X_MULTIPLIER",
                    },
                    {
                        "category": "Door Sweep / Shoe",
                        "specified": 'ZERO 39A, 42"',
                        "part_number": "ZERO-39A-42",
                        "cost_source": "MANUAL",
                    },
                    {
                        "category": "Seal / Weatherstrip",
                        "specified": "ZERO 188S BK, 18'",
                        "part_number": "ZERO-188S-BK-18ft",
                        "cost_source": "MANUAL",
                    },
                    {
                        "category": "Exit Device",
                        "specified": "VON DUPRIN 99EO",
                        "part_number": "VON-DUPRIN-99EO-42-626",
                        "manufacturer": "Von Duprin",
                        "cost_source": "DISTRIBUTOR_MANUAL",
                    },
                ],
            }
        ]
    }
    lines = [
        {
            "line_id": "01-006",
            "part_number": "PEMKO-275A-42",
            "description": "Threshold, PEMKO 275A, 42 inches",
            "quantity": 1,
            "cost": None,
            "cost_source": "MANUAL",
            "source_page": 15,
        },
        {
            "line_id": "01-007",
            "part_number": "ZERO-39A-42",
            "description": "Door shoe/sweep, Zero 39A, 42 inches",
            "quantity": 1,
            "cost": None,
            "cost_source": "MANUAL",
            "source_page": 15,
        },
        {
            "line_id": "01-008",
            "part_number": "ZERO-188S-BK-18ft",
            "description": "Seal/weatherstrip, Zero 188S, black, 18 feet",
            "quantity": 1,
            "cost": None,
            "cost_source": "MANUAL",
            "source_page": 15,
        },
        {
            "line_id": "01-002",
            "part_number": "VON-DUPRIN-99EO-42-626",
            "description": "Exit device, Von Duprin 99EO",
            "quantity": 1,
            "cost": None,
            "cost_source": "DISTRIBUTOR_MANUAL",
        },
    ]
    (root / "extracted" / "hardware_sets.json").write_text(json.dumps(hw), encoding="utf-8")
    (root / "priced" / "line_items.json").write_text(
        json.dumps({"lines": lines}), encoding="utf-8"
    )

    import cbc.shared.storage as storage_mod

    monkeypatch.setattr(storage_mod, "project_dir", lambda s: tmp_path / "projects" / s)

    stats = list_x_backfill.backfill_priced_lines(slug)
    assert stats["filled"] == 3

    updated = json.loads((root / "priced" / "line_items.json").read_text(encoding="utf-8"))
    by_part = {row["part_number"]: row for row in updated["lines"]}
    for part in ("PEMKO-275A-42", "ZERO-39A-42", "ZERO-188S-BK-18ft"):
        row = by_part[part]
        assert row["cost_source"] == "LIST_X_MULTIPLIER"
        assert row["cost"] and row["cost"] > 0
        assert row["sale_ea"] and row["sale_ea"] > 0
        assert row["source_page"] == 15
    assert by_part["VON-DUPRIN-99EO-42-626"]["cost"] is None
    assert by_part["VON-DUPRIN-99EO-42-626"]["cost_source"] == "DISTRIBUTOR_MANUAL"


def test_a_missing_price_book_skips_the_backfill_instead_of_failing_the_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The backfill is an enhancement, so its absence must not fail a priced quote.

    `_book()` called `resolve_pdf_path` unguarded, so a missing PDF raised
    `FileNotFoundError` out of `sync_results` and the worker recorded
    `sync_failed`. A job whose Claude pass had already written valid line items
    was killed three times over a book nobody had shipped, at $1.78 an attempt.
    """
    from cbc.shared import pdfpages

    hager_list_price._book.cache_clear()

    def missing(path: str):
        raise FileNotFoundError(f"PDF not found: {path}.")

    monkeypatch.setattr(pdfpages, "resolve_pdf_path", missing)
    try:
        assert hager_list_price.book_available() is False
        assert hager_list_price.lookup_ngp_list_price("431S", width_in=42) is None
        assert hager_list_price.lookup_ngp_list_price("785S") is None
    finally:
        hager_list_price._book.cache_clear()


@needs_the_book
def test_the_book_is_found_again_once_it_is_back() -> None:
    """The miss is cached per-process, so clearing it must restore service."""
    hager_list_price._book.cache_clear()
    assert hager_list_price.book_available() is True
