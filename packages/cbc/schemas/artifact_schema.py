"""Lightweight JSON Schema checks for extracted artifacts (no jsonschema dep).

Claude Code Agent calls cannot use Anthropic Messages `output_config` structured
outputs. These schemas + validate-on-write are the substitute: reject bad JSON
at save_artifact / PostToolUse instead of paying for a full regenerate later.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

SCHEMA_DIR = Path(__file__).resolve().parent / "artifacts"

# Relative project path → schema filename
PATH_SCHEMAS: dict[str, str] = {
    "extracted/scope_metadata.json": "scope_metadata.schema.json",
    "extracted/scope_summary.json": "scope_summary.schema.json",
    "extracted/door_schedule.json": "door_schedule.schema.json",
    "priced/line_items.json": "line_items.schema.json",
}


@lru_cache(maxsize=8)
def _load_schema(name: str) -> dict[str, Any]:
    path = SCHEMA_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


def schema_for_path(rel_path: str) -> dict[str, Any] | None:
    key = rel_path.replace("\\", "/").lstrip("/")
    name = PATH_SCHEMAS.get(key)
    if not name:
        return None
    return _load_schema(name)


def _type_ok(value: Any, expected: str | list[str]) -> bool:
    kinds = expected if isinstance(expected, list) else [expected]
    for kind in kinds:
        if kind == "null" and value is None:
            return True
        if kind == "string" and isinstance(value, str):
            return True
        if kind == "boolean" and isinstance(value, bool):
            return True
        if kind == "array" and isinstance(value, list):
            return True
        if kind == "object" and isinstance(value, dict):
            return True
        if kind in ("integer", "number") and isinstance(value, (int, float)) and not isinstance(
            value, bool
        ):
            return True
    return False


def _resolve(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        name = ref.rsplit("/", 1)[-1]
        resolved = dict((root.get("$defs") or {}).get(name) or {})
        extra = {key: value for key, value in schema.items() if key != "$ref"}
        resolved.update(extra)
        return resolved
    return schema


def _validate_object(
    data: dict[str, Any], schema: dict[str, Any], path: str, root: dict[str, Any]
) -> list[str]:
    problems: list[str] = []
    required = schema.get("required") or []
    for key in required:
        if key not in data:
            problems.append(f"{path}: missing required property {key!r}")
    min_props = schema.get("minProperties")
    if isinstance(min_props, int) and len(data) < min_props:
        problems.append(f"{path}: expected at least {min_props} properties")
    props = schema.get("properties") or {}
    if schema.get("additionalProperties") is False:
        for key in data:
            if key not in props:
                problems.append(f"{path}: unexpected property {key!r}")
    for key, prop_schema in props.items():
        if key not in data:
            continue
        problems.extend(_validate(data[key], prop_schema, f"{path}.{key}", root))
    return problems


def _validate(data: Any, schema: dict[str, Any], path: str, root: dict[str, Any]) -> list[str]:
    schema = _resolve(schema, root)
    if "oneOf" in schema:
        for option in schema["oneOf"]:
            if not _validate(data, option, path, root):
                return []
        return [f"{path}: does not match any allowed shape"]
    expected = schema.get("type")
    if expected is not None and not _type_ok(data, expected):
        return [f"{path}: expected type {expected!r}"]
    problems: list[str] = []
    if isinstance(data, dict) and (
        expected == "object" or "properties" in schema or "required" in schema
    ):
        problems.extend(_validate_object(data, schema, path, root))
    items = schema.get("items")
    if isinstance(data, list) and isinstance(items, dict):
        for index, item in enumerate(data):
            problems.extend(_validate(item, items, f"{path}[{index}]", root))
    return problems


def validate_instance(data: Any, schema: dict[str, Any], *, label: str = "artifact") -> list[str]:
    """Return human-readable problems; empty list means OK."""
    return _validate(data, schema, label, schema)


def validate_artifact_path(rel_path: str, data: Any) -> list[str]:
    schema = schema_for_path(rel_path)
    if schema is None:
        return []
    return validate_instance(data, schema, label=rel_path)


def validate_artifact_text(rel_path: str, content: str) -> list[str]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        return [f"{rel_path}: not valid JSON ({exc})"]
    return validate_artifact_path(rel_path, data)
