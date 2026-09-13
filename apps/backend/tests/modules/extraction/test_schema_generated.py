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
