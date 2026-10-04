"""Normalize LLM shape mistakes before door_schedule / div10 schema gates."""
from __future__ import annotations

import json

from cbc.modules.extraction.api.artifact_schema import (
    prepare_artifact_text,
    validate_artifact_path,
)
from cbc.modules.extraction.api.claude_output import Div10Takeoff, DoorSchedule, Opening
from cbc.modules.extraction.api.normalize_artifacts import (
    normalize_div10_takeoff_payload,
    normalize_line_items_payload,
    normalize_opening_dict,
    normalize_page_size,
    normalize_priced_quote_payload,
)
from cbc.modules.extraction.api.validation.contracts import parse_file


def test_page_size_array_becomes_object() -> None:
    assert normalize_page_size([2448.0, 1584.0]) == {"width": 2448.0, "height": 1584.0}


def test_thickness_relocates_into_notes() -> None:
    opening = normalize_opening_dict(
        {
            "door_number": "1",
            "thickness": '1 3/4"',
            "page_size": [100.0, 200.0],
            "notes": "DINING",
        }
    )
    assert "thickness" not in opening
    assert 'Thickness: 1 3/4"' in opening["notes"]
    assert opening["page_size"] == {"width": 100.0, "height": 200.0}


def test_opening_model_accepts_coerced_shapes() -> None:
    opening = Opening.model_validate(
        {
            "door_number": "101",
            "thickness": "1-3/4",
            "page_size": [2448, 1584],
        }
    )
    assert opening.page_size == {"width": 2448.0, "height": 1584.0}
    assert opening.notes and "Thickness:" in opening.notes


def test_true_hallucination_still_fails_schema() -> None:
    problems = validate_artifact_path(
        "extracted/line_items.json",
        {"openings": [{"door_number": "101", "hallucinated_price": "12.00"}]},
    )
    assert problems


def test_thickness_and_array_page_size_pass_after_normalize() -> None:
    raw = {
        "openings": [
            {
                "door_number": "1",
                "thickness": '1 3/4"',
                "page_size": [2448.0, 1584.0],
                "source_page": 19,
            }
        ]
    }
    normalized = normalize_line_items_payload(raw)
    assert validate_artifact_path("extracted/line_items.json", normalized) == []
    DoorSchedule.parse_payload(raw)  # before-validator path


def test_prepare_artifact_text_rewrites_payload() -> None:
    content = json.dumps(
        {
            "openings": [
                {
                    "door_number": "2",
                    "thickness": "1.75",
                    "page_size": [10, 20],
                }
            ]
        }
    )
    cleaned, problems = prepare_artifact_text("extracted/line_items.json", content)
    assert problems == []
    data = json.loads(cleaned)
    assert "thickness" not in data["openings"][0]
    assert data["openings"][0]["page_size"] == {"width": 10.0, "height": 20.0}


def test_page_size_schema_requires_width_height() -> None:
    problems = validate_artifact_path(
        "extracted/line_items.json",
        {"openings": [{"door_number": "1", "page_size": {"units": "pt"}}]},
    )
    assert problems


def test_div10_object_flags_and_line_items_are_coerced() -> None:
    raw = {
        "div10_in_scope": True,
        "status": "extracted",
        "line_items": [
            {
                "product_type": "mirror",
                "manufacturer": "Bobrick",
                "model": "B-165-1836",
                "quantity": 1,
                "description": "Mirror",
                "bbox": [1, 2, 3, 4],
                "flags": [{"type": "info", "message": "check elevations"}],
            }
        ],
        "flags": [
            {
                "type": "info",
                "severity": "low",
                "message": "grab bars not on schedule",
            }
        ],
    }
    normalized = normalize_div10_takeoff_payload(raw)
    assert "line_items" not in normalized
    assert normalized["flags"] == ["info: grab bars not on schedule"]
    item = normalized["items"][0]
    assert item["specified_model"] == "B-165-1836"
    assert item["qty"] == 1
    assert "bbox" not in item
    assert "Description: Mirror" in item["notes"]
    assert item["flags"] == ["info: check elevations"]

    cleaned, problems = prepare_artifact_text(
        "extracted/div10_takeoff.json", json.dumps(raw)
    )
    assert problems == []
    parsed = Div10Takeoff.parse_payload(json.loads(cleaned))
    assert len(parsed.items) == 1
    assert parsed.items[0].specified_model == "B-165-1836"
    assert parsed.flags == ["info: grab bars not on schedule"]
    assert parse_file("div10_takeoff", raw).items[0].qty == 1.0


def test_priced_line_items_alias_is_coerced_to_lines() -> None:
    from cbc.modules.extraction.api.claude_output import PricedQuote

    raw = {
        "project": "demo",
        "line_items": [
            {
                "line_id": "G1-01",
                "group": "GROUP 1",
                "group_type": "door",
                "quantity": 1,
                "cost_source": "MANUAL",
                "part_number": '700 83"',
                "description": "IVES hinge",
                "door_mark": "01",
                "door_description": "Restroom",
                "confidence": 0.9,
                "cost_source_detail": "Allegion via Banner",
                "source_page": 14,
            }
        ],
    }
    normalized = normalize_priced_quote_payload(raw)
    assert "line_items" not in normalized
    assert len(normalized["lines"]) == 1
    row = normalized["lines"][0]
    assert row["mark"] == "01"
    assert "door_mark" not in row
    assert "Door description: Restroom" in row["notes"]
    quote = PricedQuote.parse_payload(raw)
    assert len(quote.lines) == 1
    text, problems = prepare_artifact_text(
        "priced/line_items.json", json.dumps(raw)
    )
    assert problems == []
    rewritten = json.loads(text)
    assert "lines" in rewritten and "line_items" not in rewritten
