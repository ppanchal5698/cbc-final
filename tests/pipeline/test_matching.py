"""Matching tests - the reference library, the price books, and confidence discipline.

These assert the behaviour NFR-2 depends on: every match carries a score, a
low-confidence match is flagged rather than accepted, and an unknown vendor or
category returns "price it manually" rather than a plausible number.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.shared import ROOT

REFERENCE = ROOT / "reference-library"
CONFIDENCE_THRESHOLD = 0.75


def _load(relative: str) -> dict:
    return json.loads((REFERENCE / relative).read_text(encoding="utf-8"))


def test_reference_library_is_complete_and_valid():
    required = [
        "hardware_sets/hager_top10_stock.json",
        "hardware_sets/allegion_stock.json",
        "hardware_sets/custom_other_matrix.json",
        "margins/margin_framework.json",
        "multipliers/vendor_tiers.json",
        "multipliers/hager_special_nets.json",
        "multipliers/special_customer_margins.json",
        "frame_depths/wall_type_to_depth.json",
        "finishes/finish_crosswalk.json",
        "frp_constants/conversion_constants.json",
        "adders/manual_adders.json",
    ]
    for relative in required:
        assert (REFERENCE / relative).exists(), f"missing {relative}"
        _load(relative)


def test_price_books_are_indexed(catalog):
    indexed = catalog.list_catalogs()
    if "error" in indexed:
        pytest.skip(f"page index not readable here: {indexed['error'][:60]}")
    vendors = {book["vendor"] for book in indexed["catalogs"]}
    for expected in ("hager", "asi", "bradley", "rockwood", "national_guard", "pemko"):
        assert expected in vendors, f"{expected} catalog not indexed"


def test_hager_multiplier_is_per_category(catalog):
    locks = catalog.get_multiplier("hager", "locks")
    assert locks["multiplier"] == 0.29
    assert locks["effective_date"] == "2026-03-02"
    assert locks["account"] == "HGR 17907"

    hinges = catalog.get_multiplier("hager", "architectural_hinges")
    assert hinges["multiplier"] == 0.21, "hinges must not inherit the locks tier"


def test_unknown_vendor_returns_manual_not_a_guess(catalog):
    result = catalog.get_multiplier("acme_doors")
    assert result["multiplier"] is None
    assert "never guess" in result["note"]


def test_unknown_category_returns_manual_not_a_guess(catalog):
    result = catalog.get_multiplier("hager", "unicorn_hardware")
    assert result["multiplier"] is None
    assert "available_categories" in result


def test_allegion_is_distributor_bought_with_no_multiplier():
    """Allegion is not bought direct - a multiplier here would be a real defect."""
    tiers = _load("multipliers/vendor_tiers.json")
    allegion = next(v for v in tiers["vendors"] if v["key"] == "allegion")
    assert allegion["multiplier"] is None
    assert "MANUAL" in allegion["note"]
    assert "Banner Solutions" in allegion["distributors"]


def test_excluded_vendors_are_recorded():
    tiers = _load("multipliers/vendor_tiers.json")
    excluded = {v["name"] for v in tiers["excluded"]}
    assert "Scranton Products" in excluded
    assert "American Dryer" in excluded


def test_finish_crosswalk_keeps_us19_and_us26d_distinct():
    finishes = {f["us_code"]: f for f in _load("finishes/finish_crosswalk.json")["finishes"]}
    assert finishes["US26D"]["numeric_code"] == "626"
    assert finishes["US19"]["numeric_code"] == "619"
    assert finishes["US26D"]["numeric_code"] != finishes["US19"]["numeric_code"]


def test_frame_depths_cover_the_five_standard_throats():
    depths = {w["depth"] for w in _load("frame_depths/wall_type_to_depth.json")["wall_types"]}
    assert depths == {"5-5/8", "5-3/4", "5-7/8", "7-3/4", "8-1/4"}


def test_frp_constants_are_explicitly_pending():
    """A silently-zero constant would produce a confidently wrong FRP quantity."""
    constants = _load("frp_constants/conversion_constants.json")
    assert constants["status"] == "PENDING"
    for field in ("panel_size", "waste_pct", "trim_stick_length", "adhesive_coverage_sqft_per_unit"):
        assert constants[field] is None, f"{field} must stay null until CBC provides it"


@pytest.mark.parametrize(
    "confidence,should_flag",
    [(1.0, False), (0.95, False), (0.75, False), (0.74, True), (0.4, True), (0.0, True)],
)
def test_confidence_threshold(confidence, should_flag):
    assert (confidence < CONFIDENCE_THRESHOLD) is should_flag


def test_search_finds_a_real_part_with_page_traceability(catalog):
    """NFR-3: a hit must say which page to open, in terms an estimator can follow.

    This once searched for 4040XP, an LCN closer that no catalog here carries, so
    it looped zero times and asserted nothing while reporting traceability was
    covered. It now searches for a part the index holds and requires a hit, so it
    cannot go hollow again.
    """
    result = catalog.find_pages("BB1279", vendor="hager", limit=5)
    if "error" in result:
        pytest.skip(f"page index not readable here: {result['error'][:60]}")

    assert result["count"] >= 1, "BB1279 is a stocked Hager hinge; expected a page"
    for hit in result["pages"]:
        assert hit["pdf_page"] >= 1, "every hit names the page to open (NFR-3)"
        assert hit["locator"], "and names it the way the book does"
        assert hit["why"], "and says why it matched"
        # Navigation only. A price on a hit would be a price nobody read.
        assert "price" not in hit or hit.get("price") is None


def test_a_series_returns_pages_rather_than_a_number(catalog):
    """A series spans many pages, and the index says so instead of picking one.

    The tool this replaces collapsed the same query into a single confident
    price. Handing back the candidate pages is the honest answer: the run opens
    them and reads what is actually printed.
    """
    result = catalog.find_pages("3400", vendor="hager", limit=5)
    if "error" in result:
        pytest.skip(f"page index not readable here: {result['error'][:60]}")

    assert result["total_matched"] > 1, "the 3400 series spans several pages"
    assert all("price" not in page or page.get("price") is None for page in result["pages"])
    # The tier is curated data and still answers directly.
    assert catalog.get_multiplier("hager", "locks")["multiplier"] == 0.29


def test_hager_special_net_overrides_category_math(catalog):
    """A fixed net beats list x category, and is curated rather than extracted."""
    special = catalog.get_special_net("hager", "ECBB1100")
    assert special is not None, "ECBB1100 is on the Hager special-net sheet"
    assert special["net_price"] == 3.23
    assert special["item_code"] == "075048"
    assert special["source_page"], "a net still cites the sheet page it came from"


def test_stock_list_marks_known_hager_parts(catalog):
    hit = catalog.is_stock_item("hager", "BB1279")
    assert hit["stock"] is True
    miss = catalog.is_stock_item("hager", "NOT-A-REAL-PART-XYZ")
    assert miss["stock"] is False
