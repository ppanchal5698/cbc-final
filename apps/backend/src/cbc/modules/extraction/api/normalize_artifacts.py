"""Normalize common LLM shape mistakes before schema / Pydantic gates.

Agents often emit schedule columns the Opening allowlist forbids (`thickness`)
or MinerU-style `page_size: [w, h]`. Coerce those into the closed-world shape so
a repairable mistake does not fail the run; leave true hallucinations for
`extra="forbid"` to reject.
"""
from __future__ import annotations

import json
from typing import Any

# Schedule columns that appear on drawings but are not Opening fields.
# Relocate into `notes` rather than inventing top-level keys.
_STRAY_TO_NOTES: dict[str, str] = {
    "thickness": "Thickness",
    "thickness_in": "Thickness",
    "thickness_inches": "Thickness",
    "door_thickness": "Thickness",
    "thk": "Thickness",
    "extraction_notes": "Extraction notes",
}


def _append_note(notes: str | None, label: str, value: Any) -> str:
    fragment = f"{label}: {value}"
    existing = (notes or "").strip()
    if not existing:
        return fragment
    if fragment in existing:
        return existing
    return f"{existing}; {fragment}"


def normalize_page_size(value: Any) -> Any:
    """`[w, h]` / `(w, h)` → `{width, height}`; leave other shapes for validators."""
    if value is None or value == "":
        return None
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return {"width": float(value[0]), "height": float(value[1])}
        except (TypeError, ValueError):
            return value
    if isinstance(value, dict):
        out = dict(value)
        if "width" in out and "height" in out:
            try:
                out["width"] = float(out["width"])
                out["height"] = float(out["height"])
            except (TypeError, ValueError):
                pass
        return out
    return value


def normalize_opening_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Relocate stray keys into notes and coerce page_size in place."""
    opening = dict(data)
    notes = opening.get("notes")
    if notes is not None and not isinstance(notes, str):
        notes = str(notes)

    for key, label in _STRAY_TO_NOTES.items():
        if key not in opening:
            continue
        value = opening.pop(key)
        if value is None or value == "":
            continue
        notes = _append_note(notes if isinstance(notes, str) else None, label, value)

    if notes is not None:
        opening["notes"] = notes

    if "page_size" in opening:
        opening["page_size"] = normalize_page_size(opening.get("page_size"))

    return opening


def normalize_door_schedule_payload(raw: Any) -> Any:
    """Normalize openings inside an object wrapper or a bare openings array."""
    if isinstance(raw, list):
        return [
            normalize_opening_dict(item) if isinstance(item, dict) else item for item in raw
        ]
    if not isinstance(raw, dict):
        return raw
    data = dict(raw)
    for key in ("openings", "lines"):
        rows = data.get(key)
        if isinstance(rows, list):
            data[key] = [
                normalize_opening_dict(item) if isinstance(item, dict) else item for item in rows
            ]
    return data


def normalize_artifact_text(rel_path: str, content: str) -> str:
    """Return content, possibly rewritten, for known checkpoint paths."""
    key = rel_path.replace("\\", "/").lstrip("/")
    if key != "extracted/door_schedule.json":
        return content
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return content
    normalized = normalize_door_schedule_payload(data)
    if normalized is data:
        return content
    return json.dumps(normalized, indent=2, ensure_ascii=False) + "\n"
