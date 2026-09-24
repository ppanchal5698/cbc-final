"""Division 10 and FRP are line items, and stay one line item each.

They used to live in their own `takeoffs` collection while the pricing pass read
`div10_takeoff.json` and `frp_takeoff.json` as well - two stores for one item,
which is how an accessory gets quoted twice. They are openings now, carrying the
`division` that `priced_lines._group_type` and `pricing.DIVISION_BANDS` already
route on, and `line_items.json` is the only road to pricing.

The rules worth pinning: the right division, no invented FRP quantity, and a
corrected row that survives the next extraction without a second copy appearing
beside it.
"""
from __future__ import annotations

import pytest

from cbc.modules.extraction.api import specialty_takeoffs as importer


def test_accessories_and_partitions_take_their_own_spec_sections() -> None:
    """The band framework prices 10 21 and 10 28 differently."""
    assert importer._division_for("paper towel dispenser") == importer.DIVISION_ACCESSORIES
    assert importer._division_for("toilet partition") == importer.DIVISION_PARTITIONS
    assert importer._division_for("urinal screen") == importer.DIVISION_PARTITIONS
    assert importer._division_for(None) == importer.DIVISION_ACCESSORIES


def test_a_div10_item_becomes_a_priceable_line() -> None:
    fields = importer._div10_fields(
        {
            "product_type": "paper towel dispenser",
            "manufacturer": "Bobrick",
            "specified_model": "B-262",
            "location": "Restroom 102",
            "qty": 3,
            "unit": "ea",
            "source_page": 21,
            "bbox": [1.0, 2.0, 3.0, 4.0],
            "page_size": {"width": 2448.0, "height": 1584.0},
        },
        {},
    )
    assert fields["division"] == importer.DIVISION_ACCESSORIES
    assert fields["mark"] == "B-262"
    assert fields["qty"] == 3
    assert "Bobrick" in fields["description"]
    assert fields["specialty"]["kind"] == "div10"
    assert fields["specialty"]["unit"] == "ea"
    # The measured evidence travels with it, so the highlight works from the
    # same table as the doors.
    assert fields["evidence"]["bbox"] == [1.0, 2.0, 3.0, 4.0]
    assert fields["evidence"]["pageSize"] == {"width": 2448.0, "height": 1584.0}


def test_an_frp_area_carries_geometry_and_no_invented_quantity() -> None:
    """The FRP conversion constants are still an open item.

    A quantity here would be priced as though it had been measured. The geometry
    is real; the panel count is not yet derivable, and saying so is the honest
    artifact.
    """
    fields = importer._frp_fields(
        {
            "location": "Kitchen",
            "manufacturer": "Marlite",
            "perimeter_lf": 120.5,
            "inside_corners": 4,
            "outside_corners": 2,
            "wall_height_ft": 8,
            "source_page": 42,
        },
        {"status": "PENDING_CONSTANTS"},
    )
    assert fields["division"] == importer.DIVISION_FRP
    assert fields["qty"] is None
    assert fields["mark"] is None, "an FRP area is not a numbered opening"
    assert fields["specialty"]["perimeterLf"] == 120.5
    assert fields["specialty"]["insideCorners"] == 4
    assert fields["specialty"]["status"] == "PENDING_CONSTANTS"


def test_flags_put_a_row_in_front_of_the_estimator() -> None:
    clean = importer._div10_fields({"product_type": "mirror", "qty": 1}, {})
    flagged = importer._div10_fields(
        {"product_type": "mirror", "qty": 1, "flags": ["bbox_row_not_found"]}, {}
    )
    assert importer._status_for(clean) == "clear"
    assert importer._status_for(flagged) == "needs_look"


def test_two_rows_sharing_a_model_get_different_keys() -> None:
    """This bid really does carry two `KAY 3741` soap dispensers on page 21."""
    seen: dict[str, int] = {}
    row = {"mark": "3741", "specialty": {"kind": "div10"}, "evidence": {"sourcePage": 21}}
    assert importer._key(dict(row), seen) != importer._key(dict(row), seen)


def test_the_same_row_keys_the_same_way_across_runs() -> None:
    row = {"mark": "B-262", "specialty": {"kind": "div10"}, "evidence": {"sourcePage": 21}}
    assert importer._key(dict(row), {}) == importer._key(dict(row), {})


def test_a_different_page_is_a_different_row() -> None:
    seen: dict[str, int] = {}
    first = importer._key(
        {"mark": "B-262", "specialty": {"kind": "div10"}, "evidence": {"sourcePage": 21}}, seen
    )
    second = importer._key(
        {"mark": "B-262", "specialty": {"kind": "div10"}, "evidence": {"sourcePage": 42}}, seen
    )
    assert first != second
