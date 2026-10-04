"""A price grid edited one cell at a time is written one cell at a time.

The settings screen posted the entire lite-kit document - twenty tables, several
thousand prices - to change a single number. Two admins editing different tables
overwrote each other, because each sent back the copy they had loaded, and the
audit entry could record only a table count: "who changed this price, and from
what?" had no answer, which is the question NFR-3 exists to answer.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from cbc.modules.pricing.domain.reference_updates import LiteKitCell
from cbc.modules.pricing.features.LiteKit import _set_cell


def _doc():
    return {
        "note": "List prices. Apply the NGP multiplier.",
        "tables": [
            {"models": "L-FRA100", "prices": {"4": {"6": 113, "8": 113}}},
            {"models": "LO-PRO", "prices": {"4": {"6": 200}}},
        ],
    }


def test_one_cell_changes_and_nothing_else_moves():
    document, before = _set_cell(_doc(), LiteKitCell(table=0, width=8, height=4, price=121))

    assert before == 113, "the replaced price is reported so the audit can name it"
    assert document["tables"][0]["prices"]["4"] == {"6": 113, "8": 121}
    assert document["tables"][1]["prices"] == {"4": {"6": 200}}, "another table moved"
    assert document["note"], "the prose fields survive"


def test_a_size_with_no_price_yet_can_be_filled_in():
    document, before = _set_cell(_doc(), LiteKitCell(table=0, width=10, height=6, price=99))

    assert before is None
    assert document["tables"][0]["prices"]["6"] == {"10": 99}


def test_a_table_that_does_not_exist_is_refused():
    with pytest.raises(HTTPException) as caught:
        _set_cell(_doc(), LiteKitCell(table=9, width=6, height=4, price=1))
    assert caught.value.status_code == 404


@pytest.mark.parametrize(
    "kwargs",
    [
        {"table": -1, "width": 6, "height": 4, "price": 1},
        {"table": 0, "width": 0, "height": 4, "price": 1},
        {"table": 0, "width": 6, "height": 4, "price": -1},
    ],
)
def test_nonsense_never_reaches_the_document(kwargs):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        LiteKitCell(**kwargs)
