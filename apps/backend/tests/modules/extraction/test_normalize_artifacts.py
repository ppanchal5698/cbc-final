"""Normalize LLM shape mistakes before door_schedule schema gates."""
from __future__ import annotations

import json

from cbc.modules.extraction.api.artifact_schema import (
    prepare_artifact_text,
    validate_artifact_path,
)
from cbc.modules.extraction.api.claude_output import DoorSchedule, Opening
from cbc.modules.extraction.api.normalize_artifacts import (
    normalize_door_schedule_payload,
    normalize_opening_dict,
    normalize_page_size,
)


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
        "extracted/door_schedule.json",
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
    normalized = normalize_door_schedule_payload(raw)
    assert validate_artifact_path("extracted/door_schedule.json", normalized) == []
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
    cleaned, problems = prepare_artifact_text("extracted/door_schedule.json", content)
    assert problems == []
    data = json.loads(cleaned)
    assert "thickness" not in data["openings"][0]
    assert data["openings"][0]["page_size"] == {"width": 10.0, "height": 20.0}


def test_page_size_schema_requires_width_height() -> None:
    problems = validate_artifact_path(
        "extracted/door_schedule.json",
        {"openings": [{"door_number": "1", "page_size": {"units": "pt"}}]},
    )
    assert problems
