"""A part the estimator names on a line is looked up the way the take-off's are."""
from __future__ import annotations

import asyncio

from cbc.modules.pricing.domain.calc import cost_from_list
from cbc.modules.quoting.features import MatchAndPrice
from tests.modules.quoting.domain.ladder_test import sources

HINGE = {"lineKey": "2:01", "group": "02", "division": "08 71 00", "finish": "626", "qty": 9,
         "qtyPerOpening": 3, "unit": "EA", "openings": ["101", "103", "104"],
         "description": "Hager equal to IVES 5BB1 HINGE 4.5 X 4.5 NRP"}


def _priced(monkeypatch, doc):
    async def fake_sources(project, lines):
        return sources()

    monkeypatch.setattr(MatchAndPrice, "_sources", fake_sources)
    return asyncio.run(MatchAndPrice.price_named_part({}, doc))


def test_the_equal_an_estimator_names_is_priced_off_its_book(monkeypatch) -> None:
    """Evernorth: Hager BB1279 named for Ives 5BB1 - the Ives in the description
    is what it stands in for, not what it is."""
    priced, offered = _priced(monkeypatch, {**HINGE, "part": "BB1279", "manufacturer": "Hager"})
    assert priced["costSource"] == "LIST_X_MULTIPLIER" and offered == {}
    assert priced["cost"] == cost_from_list(23.76, 0.21)["cost"] and priced["listPrice"] == 23.76


def test_an_allegion_part_named_by_hand_is_not_priced_as_something_else(monkeypatch) -> None:
    assert _priced(monkeypatch, {**HINGE, "part": "5BB1", "manufacturer": "IVES"}) == ({}, {})


def test_a_named_part_with_several_prices_offers_them_to_choose(monkeypatch) -> None:
    """Evernorth's Hager 5100: more than one row, so the estimator picks (FR-8)."""
    closer = {**HINGE, "lineKey": "2:04", "part": "5100", "manufacturer": "Hager", "finish": "ALM",
              "description": "Hager equal to LCN 4040XP SURFACE CLOSER"}
    priced, offered = _priced(monkeypatch, closer)
    assert priced == {} and len(offered["closeMatches"]) == 2
    assert {m["cost"] for m in offered["closeMatches"]} == {cost_from_list(440.71, 0.30)["cost"],
                                                           cost_from_list(512.00, 0.30)["cost"]}
