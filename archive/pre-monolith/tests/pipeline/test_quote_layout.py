"""FR-7's layout, and the substitution note that used to fall out of it.

Two renderers fed one template and disagreed. The skill script grouped by door,
as FR-7 asks; the API path - the one behind `/render` and `/pdf`, which is what a
customer actually receives - collapsed each section into one group named after
the section, and built its line dicts by hand with no key for
`substitution_note`.

So "grouped by door with subtotals" was true only of the path nobody sees, and a
direct equal printed to a customer as the substituted part with no mention that
anything had been substituted - while `.claude/rules/accuracy-trust.md` requires
that note on every one.
"""
from __future__ import annotations

from cbc.domain import quote_layout as layout


def line(**fields):
    return layout.line(**{"description": "x", **fields})


def test_lines_are_grouped_by_door_with_a_subtotal_each() -> None:
    """FR-7, stated. The API path produced one group per *section*."""
    blocks = layout.blocks([
        line(group="Door 101", division="08 11 00", ext_price=100.0),
        line(group="Door 101", division="08 71 00", ext_price=50.0),
        line(group="Door 102", division="08 11 00", ext_price=200.0),
    ])
    doors = blocks[0]["groups"]
    assert [g["name"] for g in doors] == ["Door 101", "Door 102"]
    assert doors[0]["subtotal"] == 150.0
    assert doors[1]["subtotal"] == 200.0


def test_a_substitution_note_survives_into_the_document() -> None:
    """The accuracy-trust requirement the customer-facing path dropped."""
    blocks = layout.blocks([
        line(group="Door 101", division="08 71 00", ext_price=74.0,
             substitution_note="specified Von Duprin 99; offering Hager 4500"),
    ])
    printed = blocks[0]["groups"][0]["lines"][0]
    assert printed["substitution_note"] == "specified Von Duprin 99; offering Hager 4500"


def test_the_line_constructor_always_has_a_place_for_the_note() -> None:
    """Building line dicts by hand is how the note went missing."""
    assert "substitution_note" in layout.line(description="anything")


def test_restroom_accessories_are_their_own_block() -> None:
    """FR-7: "a separate restroom-accessories block"."""
    blocks = layout.blocks([
        line(group="Door 101", division="08 11 00", ext_price=100.0),
        line(division="10 28 00", ext_price=40.0),
    ])
    assert [b["key"] for b in blocks] == ["door", "accessories"]
    assert blocks[1]["groups"][0]["name"] == layout.SECTION_TITLES["accessories"]


def test_a_declared_group_type_beats_the_division_code() -> None:
    """A Division 10 hand dryer priced as an accessory is an accessory."""
    assert layout.section_of("10 28 00", None) == "accessories"
    assert layout.section_of("08 11 00", "accessories") == "accessories"


def test_an_unmapped_division_prints_last_rather_than_vanishing() -> None:
    blocks = layout.blocks([
        line(division="99 99 00", ext_price=10.0),
        line(group="Door 101", division="08 11 00", ext_price=100.0),
    ])
    assert [b["key"] for b in blocks] == ["door", "other"]


def test_sections_print_in_a_fixed_order() -> None:
    blocks = layout.blocks([
        line(division="06 10 00", ext_price=1.0),
        line(division="10 28 00", ext_price=1.0),
        line(group="Door 101", division="08 11 00", ext_price=1.0),
    ])
    assert [b["key"] for b in blocks] == ["door", "accessories", "frp"]


def test_a_block_subtotal_is_the_sum_of_its_doors() -> None:
    blocks = layout.blocks([
        line(group="Door 101", division="08 11 00", ext_price=100.0),
        line(group="Door 102", division="08 11 00", ext_price=200.0),
    ])
    assert blocks[0]["subtotal"] == 300.0


def test_an_unpriced_line_is_carried_not_dropped() -> None:
    """A MANUAL line has no ext_price and must still appear on the sheet."""
    blocks = layout.blocks([
        line(group="Door 101", division="08 71 00", ext_price=None,
             price_status="MANUAL"),
    ])
    group = blocks[0]["groups"][0]
    assert len(group["lines"]) == 1
    assert group["subtotal"] == 0.0


def test_freight_lands_in_a_block_rather_than_nowhere() -> None:
    """FR-7 keeps a freight line; Open Item 1 says it is usually TBD."""
    blocks = layout.blocks([line(description="Freight", division=None, ext_price=None)])
    assert blocks[0]["groups"][0]["lines"][0]["description"] == "Freight"


def test_empty_input_renders_no_blocks() -> None:
    assert layout.blocks([]) == []
