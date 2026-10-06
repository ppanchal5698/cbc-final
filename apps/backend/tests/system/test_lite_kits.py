"""A lite kit priced off National Guard's size tables (NR-1).

The size takes the cell it falls in - the next one up for an odd or fractional
inch, as the page says - and NGP's multiplier turns its list into the cost. Past
the printed table it is a vendor quote; with no multiplier in force, the
estimator's.
"""
from __future__ import annotations

import pytest

from cbc.modules.quoting.features.AddLiteKit import LiteKitCreate, lite_kit_line
from tests.shared import opshub_client

TEST_DB = "cbc_opshub_test_lite_kits"
PRICES = {"source": "pricebooks/national_guard_price_list.pdf",
          "tables": [{"pdf_page": 30, "models": "L-FRA100, LO-PRO", "widths": [6, 8, 10],
                      "prices": {"10": {"6": 113, "8": 113, "10": 121}, "12": {"6": 127, "8": 137, "10": 143}}}]}
NGP = {"key": "national_guard", "multiplier": 0.45, "tier": ".45 multiplier", "effective_date": "2026-06-08"}


def test_a_size_takes_the_next_cell_up_and_ngps_multiplier() -> None:
    line = lite_kit_line(PRICES, LiteKitCreate(table=0, width=7.5, height=11), NGP, lapsed=False)
    assert (line["listPrice"], line["cost"], line["costSource"]) == (137.0, 61.65, "LIST_X_MULTIPLIER")
    assert line["costSourceDetail"] == ('national_guard_price_list.pdf p.30: 7.5" x 11" prices at the 8" x 12" cell, '
                                        "list $137.00 x NGP 0.45 -> $61.65")
    assert line["multiplierEffectiveDate"] == "2026-06-08" and line["description"].startswith("L-FRA100, LO-PRO")


def test_past_the_table_is_a_quote_and_without_a_multiplier_the_estimators() -> None:
    past = lite_kit_line(PRICES, LiteKitCreate(table=0, width=40, height=12), NGP, lapsed=False)
    assert (past["cost"], past["costSource"]) == (None, "VENDOR_RFQ")
    for tier, lapsed, why in ((None, False, "no National Guard multiplier"), (NGP, True, "past its review window")):
        line = lite_kit_line(PRICES, LiteKitCreate(table=0, width=10, height=10), tier, lapsed)
        assert (line["cost"], line["costSource"], line["listPrice"]) == (None, "MANUAL", 121.0)
        assert why in line["costSourceDetail"]


@pytest.fixture(scope="module")
def client():
    with opshub_client(TEST_DB, isolated_storage=True) as test_client:
        yield test_client


def test_the_estimator_adds_one_to_the_quote(client) -> None:
    bid = client.post("/api/projects", json={"name": "Lite kit bid", "state": "OH"}).json()
    response = client.post(f"/api/projects/{bid['code']}/quote/lite-kits",
                           json={"table": 0, "width": 10, "height": 10, "qty": 2, "group": "101"})
    assert response.status_code == 201
    line = response.json()["line"]
    assert line["costSource"] == "LIST_X_MULTIPLIER" and line["addedByHand"] and line["qty"] == 2
    assert line["cost"] == round(line["listPrice"] * line["multiplier"], 2) and line["group"] == "101"
    assert client.post(f"/api/projects/{bid['code']}/quote/lite-kits",
                       json={"table": 999, "width": 10, "height": 10}).status_code == 404


def test_a_table_that_charges_for_a_fractional_size_charges_for_it() -> None:
    """SG-10's page: "Odd inch sizes, use next largest even size" and "Add 15% for
    Fractional Sizes" - a 9 1/2-inch lite is the 10-inch cell plus 15%."""
    prices = {"tables": [{**PRICES["tables"][0], "rules": ["Odd inch sizes, use next largest even size",
                                                           "Add 15% for Fractional Sizes"]}]}
    fraction = lite_kit_line(prices, LiteKitCreate(table=0, width=9.5, height=10), NGP, lapsed=False)
    assert (fraction["listPrice"], fraction["cost"]) == (139.15, 62.62)  # 121 + 15%, x 0.45
    assert "+ 15% for a fractional size = $139.15" in fraction["costSourceDetail"]
    whole = lite_kit_line(prices, LiteKitCreate(table=0, width=9, height=10), NGP, lapsed=False)
    assert whole["listPrice"] == 121.0, "an odd inch takes the next cell, with nothing added"
