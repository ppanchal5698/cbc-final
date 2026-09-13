"""Pydantic contracts for Claude JSON — reject before Mongo write."""
from __future__ import annotations

import pytest

from cbc.schemas.claude_output import DoorSchedule, PricedLine
from cbc.validation.contracts import COMPLETENESS_FLOOR, extraction_review_verdict, parse_file


def test_qty_string_is_coerced() -> None:
    schedule = DoorSchedule.parse_payload(
        {"openings": [{"door_number": "101", "qty": "2", "size": "3070"}]}
    )
    assert schedule.openings[0].qty == 2.0


def test_unknown_opening_field_is_rejected() -> None:
    with pytest.raises(Exception):
        DoorSchedule.parse_payload(
            {"openings": [{"door_number": "101", "hallucinated_price": "12.00"}]}
        )


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
        path = tmp_path / "thin" / "extracted" / "door_schedule.json"
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
