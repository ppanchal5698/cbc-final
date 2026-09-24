"""Pydantic contracts for Claude JSON — reject before Mongo write."""
from __future__ import annotations

import pytest

from cbc.modules.extraction.api.claude_output import DoorSchedule, PricedLine
from cbc.modules.extraction.api.validation.contracts import COMPLETENESS_FLOOR, extraction_review_verdict, parse_file


def test_qty_string_is_coerced() -> None:
    schedule = DoorSchedule.parse_payload(
        {"openings": [{"door_number": "101", "qty": "2", "size": "3070"}]}
    )
    assert schedule.openings[0].qty == 2.0


def test_keying_object_is_accepted() -> None:
    schedule = DoorSchedule.parse_payload(
        {
            "openings": [
                {
                    "door_number": "101",
                    "size": "3070",
                    "keying": {
                        "coreType": "icSmallFormat",
                        "keyway": "Schlage C",
                        "lockFunction": "storeroom",
                        "notes": None,
                    },
                }
            ]
        }
    )
    assert schedule.openings[0].keying is not None
    assert schedule.openings[0].keying.coreType == "icSmallFormat"
    assert schedule.openings[0].keying.keyway == "Schlage C"


def test_keying_string_becomes_notes() -> None:
    schedule = DoorSchedule.parse_payload(
        {"openings": [{"door_number": "101", "keying": "SFIC keyed alike"}]}
    )
    assert schedule.openings[0].keying is not None
    assert schedule.openings[0].keying.notes == "SFIC keyed alike"


def test_an_unknown_opening_field_costs_that_field_not_the_run() -> None:
    """It used to raise, which killed the whole take-off over one invented key.

    A schedule of 27 good openings was refused because a pass added a field
    nobody asked for. The value is kept where a person can see it - dropping it
    silently is what the accuracy rule forbids - and the other 27 openings live.

    The strict contract has not gone anywhere: the raw schema check still
    refuses the key outright (`test_a_hallucinated_opening_field_is_still_refused`).
    This is the repair layer, which Div10Item and PricedLine already had.
    """
    schedule = DoorSchedule.parse_payload(
        {"openings": [{"door_number": "101", "hallucinated_price": "12.00"}]}
    )
    opening = schedule.openings[0]
    assert opening.door_number == "101"
    assert "hallucinated_price=12.00" in (opening.notes or "")


def test_priced_line_rejects_boolean_cost() -> None:
    with pytest.raises(Exception):
        PricedLine.model_validate(
            {
                "line_id": "L1",
                "group": "Door 101",
                "group_type": "door",
                "quantity": 1,
                "cost_source": "MANUAL",
                "cost": True,
            }
        )


def test_low_completeness_is_needs_review(tmp_path, monkeypatch) -> None:
    from cbc.shared.config import settings
    from cbc.shared import storage

    previous = settings.storage_root
    settings.storage_root = tmp_path
    try:
        storage.scaffold("thin")
        path = tmp_path / "thin" / "extracted" / "line_items.json"
        path.write_text(
            '{"openings":[{"door_number":"101"},{"door_number":"102"}]}',
            encoding="utf-8",
        )
        assert extraction_review_verdict("thin") == "needs_review"
        assert COMPLETENESS_FLOOR == 0.5
    finally:
        settings.storage_root = previous


def test_parse_file_priced_array() -> None:
    parsed = parse_file(
        "priced_lines",
        [
            {
                "line_id": 1,
                "group": "a",
                "group_type": "other",
                "quantity": "3",
                "cost_source": "MANUAL",
            }
        ],
    )
    assert parsed.lines[0].quantity == 3.0
    assert parsed.lines[0].line_id == "1"
