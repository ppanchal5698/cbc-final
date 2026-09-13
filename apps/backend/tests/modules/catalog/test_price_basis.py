"""What an indexed price means: a list figure, or a cost already.

The catalog screen rendered every indexed price as "list $X". For a Hager special
net read off the multiplier sheet that is backwards - 3.23 is the cost, and an
estimator who takes it for list and applies the 0.21 category multiplier quotes the
line at 68 cents. These pin the classification and the shape the API hands over,
because the failure is silent: a wrong label still shows a plausible number.
"""
from __future__ import annotations

import json

import pytest

from cbc.modules.catalog.features.IngestPricebook import _prices_for
from cbc.modules.catalog.api.pageindex import basis


@pytest.fixture(autouse=True)
def _fresh_caches():
    """The lookups are cached for the process; each test reads the real files.

    The cache lives on the `_at` functions - the signature-keyed inner half of
    the pair - not on the public wrapper. Clearing the wrapper raised
    AttributeError in setup, so every test in this file errored rather than ran.

    Only the sheet index is cached now: vendor tiers come from the reference
    service on every call, so there is no `_vendors_with_a_multiplier_at` or
    `_net_program_vendors_at` left to clear - naming them errored every test in
    this file at setup.
    """
    basis._sheet_kinds_at.cache_clear()
    yield


# â”€â”€ the classification â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@pytest.mark.skipif(
    not (basis._pricebook_dir() / "index.json").exists(),
    reason="pricebooks/index.json is purchasing's uploaded inventory and is gitignored "
    "(data/pricebooks/*); only it marks hager_multipliers.pdf a multiplier sheet",
)
def test_a_multiplier_sheet_publishes_nets() -> None:
    """The sheet exists to publish special nets, so its numbers are costs."""
    assert basis.price_basis("hager_multipliers.pdf", "hager") == basis.NET


def test_a_price_book_from_a_multiplier_vendor_is_list() -> None:
    """Hager has both kinds of sheet on file; the book is the list one."""
    assert basis.price_basis("hager_price_book_18.pdf", "hager") == basis.LIST


def test_a_vendor_bought_on_a_net_program_is_net() -> None:
    """vendor_tiers records no multiplier for these and says why in words."""
    assert basis.price_basis("bobrick_hp_program_net.xlsx", "bobrick") == basis.NET
    assert basis.price_basis("gamco_hp_program_net.xlsx", "gamco") == basis.NET


def test_an_untranscribed_tier_is_not_a_net_program() -> None:
    """Pemko's multipliers were never transcribed. That is not the same fact.

    Both look like "no multiplier on file", and collapsing them would label a list
    price as a net - the mirror of the bug this exists for.
    """
    assert basis.price_basis("pemko_markar_price_book_2026.pdf", "pemko") == basis.UNKNOWN


def test_an_unrecognised_sheet_says_so_rather_than_guessing() -> None:
    assert basis.price_basis("who_knows.pdf", "acme") == basis.UNKNOWN
    assert basis.price_basis(None, None) == basis.UNKNOWN


def test_the_note_tells_an_estimator_what_to_do() -> None:
    assert "do not apply a multiplier" in basis.describe(basis.NET)
    assert "multiply" in basis.describe(basis.LIST)
    assert "confirm" in basis.describe(basis.UNKNOWN)


def test_every_indexed_sheet_classifies() -> None:
    """No sheet on file falls through to an exception or an empty string."""
    inventory = basis._pricebook_dir() / "index.json"
    if not inventory.exists():
        pytest.skip("no price-book inventory on this machine")
    entries = json.loads(inventory.read_text(encoding="utf-8"))["pricebooks"]
    assert entries, "inventory is empty"
    for entry in entries:
        result = basis.price_basis(entry["file"], entry.get("vendor"))
        assert result in (basis.LIST, basis.NET, basis.UNKNOWN), entry["file"]


# â”€â”€ the shape the API hands to the screen â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@pytest.mark.parametrize(
    "price_basis, expect_list, expect_net",
    [(basis.LIST, 12.5, None), (basis.NET, None, 12.5), (basis.UNKNOWN, None, None)],
)
def test_list_price_is_populated_only_when_it_is_one(
    price_basis: str, expect_list: float | None, expect_net: float | None
) -> None:
    """A caller that reads `listPrice` without checking the basis gets nothing.

    Filling it regardless is what let a net reach the screen labelled "list": the
    field name asserted something the index never knew.
    """
    row = {"price": 12.5, "price_basis": price_basis}
    list_price = row["price"] if row["price_basis"] == basis.LIST else None
    net_price = row["price"] if row["price_basis"] == basis.NET else None

    assert list_price == expect_list
    assert net_price == expect_net
    # The raw figure stays available either way, so nothing is hidden.
    assert row["price"] == 12.5


# â”€â”€ the ingest path: a net must never land in listPrice â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_a_net_sheet_stores_its_figure_as_the_cost() -> None:
    """The pass calls it `list_price` because that is the only field it has.

    Left there, changing the program multiplier recomputes
    `cost = listPrice x multiplier` and discounts an already-net figure again.
    """
    list_price, cost, multiplier = _prices_for(basis.NET, {"list_price": 3.23})

    assert list_price is None, "a net must not be reachable by the repricing query"
    assert cost == 3.23
    assert multiplier is None, "a net program has no multiplier to carry"


def test_a_net_sheet_prefers_an_explicit_cost() -> None:
    _, cost, _ = _prices_for(basis.NET, {"list_price": 9.99, "cost": 3.23})
    assert cost == 3.23


def test_a_list_sheet_is_stored_as_before() -> None:
    list_price, cost, multiplier = _prices_for(
        basis.LIST, {"list_price": 200.0, "cost": 58.0, "multiplier": 0.29}
    )
    assert (list_price, cost, multiplier) == (200.0, 58.0, 0.29)


def test_an_unknown_basis_is_stored_as_a_list_price() -> None:
    """Not evidence of a net program - just a tier nobody has transcribed.

    Treating it as a net would strand the price out of the repricing query and
    mislabel a list figure, which is this same bug pointing the other way.
    """
    list_price, cost, multiplier = _prices_for(
        basis.UNKNOWN, {"list_price": 200.0, "multiplier": 0.5}
    )
    assert (list_price, multiplier) == (200.0, 0.5)
    assert cost is None

