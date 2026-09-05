"""Derive the artifact JSON Schemas from the Pydantic contracts.

There were two hand-maintained copies of every artifact shape: the models in
`claude_output.py` and the documents in `artifacts/*.schema.json`. 113 field
declarations, in two files, with no generator and no parity test. They drifted -
`parse_schedule.py` grew `size_notation`, `row_bbox` and `cell_boxes`, the
Ops-Hub export grew `confirmed_by`, and neither copy learned about them - and a
production bid run died on `Extra inputs are not permitted` against a file the
system had written itself.

The models are the source. This module renders the same documents from them, and
`tests/pipeline/test_schema_generated.py` fails if the committed files differ
from what it renders. Adding a field to a model and forgetting the schema is now
a red test rather than a dead run.

Regenerate:

    python -m cbc.schemas.artifact_contracts
"""
from __future__ import annotations

import json
import types
import typing
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from cbc.schemas.claude_output import Opening, PricedLine, ScopeMetadata, ScopeSummary

SCHEMA_DIR = Path(__file__).resolve().parent / "artifacts"

# Python annotation -> the JSON Schema type names the artifact validator
# understands (`artifact_schema.py::_type_ok`).
_SCALARS: dict[Any, str] = {
    str: "string",
    bool: "boolean",
    float: "number",
    int: "integer",
    dict: "object",
    list: "array",
}

# Three fields accept a string on the wire because the model coerces them: an
# agent that writes "2" for a quantity is corrected, not rejected
# (`claude_output._coerce_number`). The schema has to permit what the model
# accepts, or the write-time hook rejects a payload the import would have taken.
_COERCED_TO_STRING = {"qty", "confidence", "quantity", "cost", "margin", "sale_ea",
                      "ext_price", "multiplier"}

# The mirror image: `line_id` is typed `str | None` but its before-validator
# stringifies whatever arrives, so `{"line_id": 1}` is valid input and a
# string-only schema would reject a payload the importer accepts.
_STRINGIFIED = {"line_id": ["string", "integer", "number", "null"]}


def _type_names(annotation: Any) -> list[str]:
    """JSON Schema type names for one annotation, nullability included."""
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        names: list[str] = []
        for arg in typing.get_args(annotation):
            for name in _type_names(arg):
                if name not in names:
                    names.append(name)
        return names
    if annotation is type(None):
        return ["null"]
    if origin in (list, dict):
        return [_SCALARS[origin]]
    if annotation in _SCALARS:
        return [_SCALARS[annotation]]
    if annotation is Any:
        return []
    raise TypeError(f"no JSON Schema mapping for {annotation!r}")


def _property(name: str, annotation: Any) -> dict[str, Any]:
    if name in _STRINGIFIED:
        return {"type": _STRINGIFIED[name]}
    names = _type_names(annotation)
    if name in _COERCED_TO_STRING and "string" not in names:
        names.insert(names.index("null") if "null" in names else len(names), "string")
    # `bool` is a subtype of `int` in Python but not in JSON Schema; an integer
    # annotation that also permits a number keeps both, in that order.
    return {"type": names[0] if len(names) == 1 else names}


def properties_of(model: type[BaseModel]) -> dict[str, Any]:
    """One JSON Schema `properties` block, in field-declaration order."""
    return {
        name: _property(name, field.annotation)
        for name, field in model.model_fields.items()
    }


def _rows_envelope(model: type[BaseModel], *, defs_name: str, rows_key: str,
                   extra: dict[str, Any], schema_id: str, title: str) -> dict[str, Any]:
    """An artifact that is either `{rows: [...]}` or a bare `[...]`.

    Both shapes reach the importer (`_normalize_schedule_payload` has always
    taken either), so both are valid here.
    """
    row = {"$ref": f"#/$defs/{defs_name}"}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_id,
        "title": title,
        "oneOf": [
            {
                "type": "object",
                "properties": {rows_key: {"type": "array", "items": row}, **extra},
                "additionalProperties": True,
            },
            {"type": "array", "items": row},
        ],
        "$defs": {
            defs_name: {
                "type": "object",
                # Unknown keys are refused so a hallucinated field is caught at
                # the write, not carried into Mongo (NFR-2).
                "additionalProperties": False,
                "properties": properties_of(model),
            }
        },
    }


def door_schedule_schema() -> dict[str, Any]:
    return _rows_envelope(
        Opening,
        defs_name="opening",
        rows_key="openings",
        extra={
            "lines": {"type": "array", "items": {"$ref": "#/$defs/opening"}},
            "no_scope_reason": {"type": ["string", "null"]},
            "sheet": {"type": ["string", "null"]},
            "source_file": {"type": ["string", "null"]},
            "door_schedule_found": {"type": ["boolean", "null"]},
        },
        schema_id="cbc.extracted.door_schedule",
        title="door_schedule",
    )


def line_items_schema() -> dict[str, Any]:
    return _rows_envelope(
        PricedLine,
        defs_name="priced_line",
        rows_key="lines",
        extra={},
        schema_id="cbc.priced.line_items",
        title="line_items",
    )


def _flat_schema(model: type[BaseModel], *, schema_id: str, title: str,
                 required: list[str] | None = None,
                 min_properties: int | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_id,
        "title": title,
        "type": "object",
        "properties": properties_of(model),
        # Metadata and scope files carry provenance keys the model ignores
        # (`extra="ignore"`), so unknown keys here are tolerated.
        "additionalProperties": True,
    }
    if required:
        schema["required"] = required
    if min_properties is not None:
        schema["minProperties"] = min_properties
    return schema


def scope_metadata_schema() -> dict[str, Any]:
    return _flat_schema(
        ScopeMetadata,
        schema_id="cbc.extracted.scope_metadata",
        title="scope_metadata",
        # An empty object is not metadata. The model cannot say this - every field
        # is optional on its own - so the guard stays here.
        min_properties=1,
    )


def scope_summary_schema() -> dict[str, Any]:
    return _flat_schema(
        ScopeSummary,
        schema_id="cbc.extracted.scope_summary",
        title="scope_summary",
        required=["frp_in_scope"],
    )


SCHEMAS = {
    "door_schedule.schema.json": door_schedule_schema,
    "line_items.schema.json": line_items_schema,
    "scope_metadata.schema.json": scope_metadata_schema,
    "scope_summary.schema.json": scope_summary_schema,
}


def render(filename: str) -> str:
    """The exact file content for one schema, newline-terminated."""
    return json.dumps(SCHEMAS[filename](), indent=2) + "\n"


def write_all() -> list[Path]:
    written = []
    for filename in SCHEMAS:
        path = SCHEMA_DIR / filename
        path.write_text(render(filename), encoding="utf-8")
        written.append(path)
    return written


if __name__ == "__main__":
    for path in write_all():
        print(f"wrote {path}")
