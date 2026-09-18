"""The artifact JSON Schemas are generated, and may not drift from the models.

A door schedule's field list used to be written out twice - once as pydantic in
`claude_output.py`, once as JSON Schema in `artifacts/*.schema.json` - 113
declarations across two files with no generator and no parity check. They drifted
exactly as you would expect: `parse_schedule.py` started emitting
`size_notation`, `row_bbox` and `cell_boxes`, the Ops-Hub export started emitting
`confirmed_by`, and neither copy was told. A bid run then died on `Extra inputs
are not permitted` against a file the system had produced itself.

`cbc.modules.extraction.api.artifact_contracts` renders the schemas from the models. These tests
fail if the committed files no longer match, so the only way to change a shape is
to change the model and regenerate:

    python -m cbc.modules.extraction.api.artifact_contracts
"""
from __future__ import annotations

import json

import pytest

from cbc.modules.extraction.api import artifact_contracts as contracts
from cbc.modules.extraction.api.artifact_schema import validate_artifact_path
from cbc.modules.extraction.api.claude_output import Opening, PricedLine


@pytest.mark.parametrize("filename", sorted(contracts.SCHEMAS))
def test_the_committed_schema_matches_the_model(filename: str) -> None:
    on_disk = (contracts.SCHEMA_DIR / filename).read_text(encoding="utf-8")
    assert on_disk == contracts.render(filename), (
        f"{filename} is out of date with the pydantic contract. "
        "Regenerate with: python -m cbc.modules.extraction.api.artifact_contracts"
    )


def test_every_model_field_reaches_the_schema() -> None:
    """The check that would have caught the failure directly."""
    opening = json.loads(
        (contracts.SCHEMA_DIR / "door_schedule.schema.json").read_text(encoding="utf-8")
    )["$defs"]["opening"]["properties"]
    assert set(opening) == set(Opening.model_fields)

    line = json.loads(
        (contracts.SCHEMA_DIR / "line_items.schema.json").read_text(encoding="utf-8")
    )["$defs"]["priced_line"]["properties"]
    assert set(line) == set(PricedLine.model_fields)


def test_the_schema_accepts_what_the_model_accepts() -> None:
    """A schema stricter than its model rejects work the importer would take.

    That asymmetry is the whole defect class. `flags: null` parsed fine and was
    refused at the write, because the hand-written schema said `"array"` where the
    model said `list[str] | None`.
    """
    payload = {"frp_in_scope": True, "flags": None, "divisions": None}
    from cbc.modules.extraction.api.claude_output import ScopeSummary

    ScopeSummary.model_validate(payload)  # the model takes it
    assert validate_artifact_path("extracted/scope_summary.json", payload) == []


def test_a_hallucinated_opening_field_is_still_refused() -> None:
    """Generating the schema must not have loosened the guard that matters."""
    problems = validate_artifact_path(
        "extracted/door_schedule.json",
        {"openings": [{"door_number": "101", "hallucinated_price": "12.00"}]},
    )
    assert problems, "an unknown opening key must not validate"


def test_page_size_in_schema_requires_width_and_height() -> None:
    opening = json.loads(
        (contracts.SCHEMA_DIR / "door_schedule.schema.json").read_text(encoding="utf-8")
    )["$defs"]["opening"]["properties"]["page_size"]
    assert opening.get("required") == ["width", "height"]
    assert "width" in (opening.get("properties") or {})
    assert "height" in (opening.get("properties") or {})


def test_every_field_the_deterministic_seeds_write_is_declared() -> None:
    """The seeds write artifacts that must survive their own schema gate.

    `scope_rules.apply_to` began stamping `in_scope` / `scope_rule` /
    `scope_reason` on every opening, and `Opening` is `extra="forbid"`. The
    seeds write with `atomic_write_json`, which runs no validation, so the file
    on disk looked fine and only failed when something tried to `save_artifact`
    it - with `Extra inputs are not permitted`, the exact failure this whole
    contract exists to prevent.

    Checking the writer against the model catches the class, not one instance.
    """
    from cbc.modules.extraction.api.claude_output import Div10Item, Opening
    from cbc.modules.extraction.domain import scope_rules

    rows = [{"door_number": "01", "door_material": "HM"}]
    scope_rules.apply_to(rows)
    undeclared = set(rows[0]) - set(Opening.model_fields)
    assert not undeclared, f"scope_rules writes {undeclared}, which Opening forbids"

    from cbc.modules.extraction.infrastructure import specialty_parser

    item = {
        "product_type": "grab_bar", "manufacturer": "Bobrick",
        "specified_model": "B-6806", "qty": None, "unit": None, "location": None,
        "room": None, "drawing_ref": None, "finish": None, "notes": "x",
        "alternate": None, "source_page": 19, "evidence_note": "p19",
        "flags": [], "confidence": 0.85,
    }
    assert set(item) <= set(Div10Item.model_fields), (
        f"specialty_parser writes {set(item) - set(Div10Item.model_fields)}, "
        "which Div10Item forbids"
    )
    assert specialty_parser.div10_items_on_page  # the writer this mirrors exists


def test_a_seeded_schedule_passes_the_gate_it_will_be_saved_through() -> None:
    """End to end on the shape the seed actually produces."""
    from cbc.modules.extraction.api.artifact_schema import prepare_artifact_text
    from cbc.modules.extraction.api.claude_output import DoorSchedule
    from cbc.modules.extraction.domain import scope_rules

    openings = [
        {"door_number": "02", "door_material": "AL", "size": "3070",
         "room_name": "VESTIBULE", "source_file": "uploads/raw/a.pdf",
         "source_page": 16, "bbox": [1.0, 2.0, 3.0, 4.0],
         "page_size": {"width": 100.0, "height": 200.0}},
        {"door_number": "05", "door_material": "PL", "size": "3068",
         "room_name": "UNISEX WRM", "source_file": "uploads/raw/a.pdf",
         "source_page": 16, "bbox": [1.0, 2.0, 3.0, 4.0],
         "page_size": {"width": 100.0, "height": 200.0}},
    ]
    scope_rules.apply_to(openings)
    payload = {"source_page": 16, "openings": openings}

    cleaned, problems = prepare_artifact_text(
        "extracted/door_schedule.json", json.dumps(payload)
    )
    assert problems == [], problems
    parsed = DoorSchedule.model_validate(json.loads(cleaned))
    assert [o.in_scope for o in parsed.openings] == [False, True]
    assert parsed.openings[0].scope_rule == "storefront"
