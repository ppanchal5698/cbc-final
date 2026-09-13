"""§4.8 snapshot freeze - a quoted line must not move when reference data edits."""
from __future__ import annotations

from cbc.services import quote as quote_service


def test_repriced_line_keeps_frozen_cost_and_margin() -> None:
    line = {
        "cost": 100.0,
        "margin": 0.27,
        "qty": 1,
        "division": "08 71 00",
        "costSource": "P21",
        "listPrice": 200.0,
        "multiplier": 0.5,
        "vendor": "Hager",
        "marginSnapshot": {
            "band": "commodity",
            "rate": 0.27,
            "overridden": False,
            "resolvedFrom": "band",
            "frozenAt": "past",
        },
        "costSnapshot": {
            "cost": 100.0,
            "costSource": "P21",
            "frozenAt": "past",
        },
    }
    # Reference-style drift on margin only - cost on the line is unchanged, so
    # the frozen margin still applies when margin is cleared to re-derive.
    line["margin"] = None

    result = quote_service.reprice([line], "OH", None)
    assert result["totals"]["subtotal"] is not None
    assert line["costSnapshot"]["cost"] == 100.0
    assert line["marginSnapshot"]["rate"] == 0.27
    assert line["sell"] == round(100 / (1 - 0.27), 2)


def test_estimator_cost_edit_refreshes_cost_snapshot() -> None:
    line = {
        "cost": 100.0,
        "margin": 0.27,
        "qty": 1,
        "division": "08 71 00",
        "costSnapshot": {"cost": 74.33, "costSource": "P21", "frozenAt": "past"},
    }
    quote_service.reprice([line], None, None)
    assert line["costSnapshot"]["cost"] == 100.0
    assert line["sell"] == round(100 / (1 - 0.27), 2)


def test_price_book_and_multiplier_snapshots_freeze_on_first_reprice() -> None:
    line = {
        "cost": 50.0,
        "margin": 0.27,
        "qty": 1,
        "division": "08 71 00",
        "listPrice": 100.0,
        "multiplier": 0.5,
        "vendor": "Hager",
        "multiplierTier": "lock",
    }
    quote_service.reprice([line], None, None)
    assert line["priceBookSnapshot"]["listPrice"] == 100.0
    assert line["multiplierTierSnapshot"]["multiplier"] == 0.5
    line["listPrice"] = 1.0
    line["multiplier"] = 0.99
    quote_service.reprice([line], None, None)
    assert line["priceBookSnapshot"]["listPrice"] == 100.0
    assert line["multiplierTierSnapshot"]["multiplier"] == 0.5
