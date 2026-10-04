"""Normalize common LLM shape mistakes before schema / Pydantic gates.

Agents often emit schedule columns the Opening allowlist forbids (`thickness`)
or a bare `page_size: [w, h]`. Coerce those into the closed-world shape so
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

    # Prefer an explicit bbox; fall back to row_bbox / union of cell_boxes.
    bbox = opening.get("bbox")
    if not _bbox_ok(bbox):
        row = opening.get("row_bbox")
        if _bbox_ok(row):
            opening["bbox"] = list(row)
        else:
            cells = opening.get("cell_boxes")
            if isinstance(cells, list):
                valid = [c for c in cells if _bbox_ok(c)]
                if valid:
                    opening["bbox"] = [
                        min(float(c[0]) for c in valid),
                        min(float(c[1]) for c in valid),
                        max(float(c[2]) for c in valid),
                        max(float(c[3]) for c in valid),
                    ]

    # Anything still unrecognised goes into notes rather than failing the write.
    # `Opening` is `extra="forbid"`, so one invented key used to kill a whole run
    # - a schedule of 27 good openings refused over a `door_swing` nobody asked
    # for. Div10Item and PricedLine already relocate; openings were the gap.
    #
    # Last, so the bbox fallback above still sees `row_bbox` / `cell_boxes`.
    stray: list[str] = []
    for key in list(opening.keys()):
        if key in _opening_fields():
            continue
        value = opening.pop(key)
        if value is None or value == "":
            continue
        stray.append(f"{key}={value}")
    if stray:
        notes = _append_note(
            notes if isinstance(notes, str) else None, "Extra", "; ".join(sorted(stray))
        )
        opening["notes"] = notes

    return opening


_OPENING_FIELDS: frozenset[str] | None = None


def _opening_fields() -> frozenset[str]:
    """What `Opening` declares, read from the model so the two cannot drift.

    Imported lazily: `claude_output` imports this module at load, so naming it
    at the top would be a cycle.
    """
    global _OPENING_FIELDS
    if _OPENING_FIELDS is None:
        from cbc.modules.extraction.api.claude_output import Opening

        _OPENING_FIELDS = frozenset(Opening.model_fields)
    return _OPENING_FIELDS


def _bbox_ok(box: Any) -> bool:
    return (
        isinstance(box, list)
        and len(box) == 4
        and all(isinstance(v, (int, float)) for v in box)
        and float(box[2]) > float(box[0])
        and float(box[3]) > float(box[1])
    )

def normalize_line_items_payload(raw: Any) -> Any:
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


# Div10Item closed allowlist — unknown keys relocate into notes.
_DIV10_ITEM_FIELDS = frozenset(
    {
        "product_type",
        "manufacturer",
        "location",
        "room",
        "drawing_ref",
        "qty",
        "unit",
        "specified_model",
        "finish",
        "notes",
        "alternate",
        "source_page",
        "source_file",
        "evidence_note",
        "flags",
        "confidence",
    }
)

_DIV10_ITEM_ALIASES: dict[str, str] = {
    "model": "specified_model",
    "model_number": "specified_model",
    "part_number": "specified_model",
    "quantity": "qty",
}


def coerce_flag_strings(value: Any) -> list[str] | None:
    """Turn flag objects / mixed arrays into plain strings for list[str] gates."""
    if value is None:
        return None
    if not isinstance(value, list):
        coerced = _flag_to_string(value)
        return [coerced] if coerced else None
    out: list[str] = []
    for item in value:
        text = _flag_to_string(item)
        if text:
            out.append(text)
    return out


def _flag_to_string(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        message = value.get("message") or value.get("note") or value.get("text")
        kind = value.get("type") or value.get("flag") or value.get("severity")
        if message and kind:
            return f"{kind}: {message}".strip()
        if message:
            return str(message).strip() or None
        if kind:
            return str(kind).strip() or None
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            return str(value)
    return str(value).strip() or None


def normalize_div10_item(data: dict[str, Any]) -> dict[str, Any]:
    """Remap aliases, coerce flags, and fold stray keys into notes."""
    item = dict(data)
    notes = item.get("notes")
    if notes is not None and not isinstance(notes, str):
        notes = str(notes)

    for src, dest in _DIV10_ITEM_ALIASES.items():
        if src not in item:
            continue
        value = item.pop(src)
        if value is None or value == "":
            continue
        if dest not in item or item.get(dest) in (None, ""):
            item[dest] = value
        else:
            notes = _append_note(notes if isinstance(notes, str) else None, dest, value)

    # Provenance / freeform fields agents emit beside the allowlist.
    for key in ("description", "mounting_notes", "line_id", "confidence_reason"):
        if key not in item:
            continue
        value = item.pop(key)
        if value is None or value == "":
            continue
        label = {
            "description": "Description",
            "mounting_notes": "Mounting",
            "line_id": "Line id",
            "confidence_reason": "Confidence",
        }[key]
        notes = _append_note(notes if isinstance(notes, str) else None, label, value)

    # Geometry / audit keys are dropped (not Opening-style notes material).
    for key in ("bbox", "page_size", "extracted_at", "row_bbox", "cell_boxes"):
        item.pop(key, None)

    stray: list[str] = []
    for key in list(item.keys()):
        if key in _DIV10_ITEM_FIELDS:
            continue
        value = item.pop(key)
        if value is None or value == "":
            continue
        stray.append(f"{key}={value}")
    if stray:
        notes = _append_note(
            notes if isinstance(notes, str) else None, "Extra", "; ".join(stray)
        )

    if notes is not None:
        item["notes"] = notes

    if "flags" in item:
        item["flags"] = coerce_flag_strings(item.get("flags"))

    return item


def normalize_div10_takeoff_payload(raw: Any) -> Any:
    """Map line_items→items, coerce object flags, and close Div10Item shape."""
    if not isinstance(raw, dict):
        return raw
    data = dict(raw)
    line_items = data.pop("line_items", None)
    if isinstance(line_items, list) and not isinstance(data.get("items"), list):
        data["items"] = line_items
    elif isinstance(line_items, list) and not data.get("items"):
        data["items"] = line_items

    rows = data.get("items")
    if isinstance(rows, list):
        data["items"] = [
            normalize_div10_item(item) if isinstance(item, dict) else item for item in rows
        ]

    if "flags" in data:
        data["flags"] = coerce_flag_strings(data.get("flags"))

    return data


# Closed-world PricedLine fields (keep in sync with claude_output.PricedLine).
_PRICED_LINE_FIELDS = frozenset(
    {
        "line_id",
        "group",
        "group_type",
        "quantity",
        "cost_source",
        "part_number",
        "part",
        "description",
        "division",
        "cost",
        "margin",
        "sale_ea",
        "ext_price",
        "basis",
        "cost_source_detail",
        "multiplier",
        "multiplier_tier",
        "multiplier_effective_date",
        "price_book_version",
        "source_page",
        "price_status",
        "added_by_hand",
        "flags",
        "substitution_note",
        "margin_overridden",
        "margin_override_reason",
        "notes",
        "vendor",
        "unit",
        "uom",
        "opening",
        "mark",
        "hw_set",
        "hardware_set",
        "catalog_page",
    }
)

_PRICED_STRAY_LABELS = {
    "door_mark": "Door mark",
    "door_description": "Door description",
    "confidence": "Confidence",
    "confidence_reason": "Confidence reason",
    "evidence_note": "Evidence",
    "manufacturer": "Manufacturer",
    "item_type": "Item type",
}


def normalize_priced_line(data: dict[str, Any]) -> dict[str, Any]:
    """Relocate agent extras into notes; keep only PricedLine allowlist keys."""
    from cbc.modules.extraction.api.manufacturer_aliases import apply_to_priced_line

    line = apply_to_priced_line(dict(data))
    notes = line.get("notes")
    if notes is not None and not isinstance(notes, str):
        notes = str(notes)

    # Common aliases the pricing agent emits beside the contract names.
    if line.get("part_number") in (None, "") and line.get("part") not in (None, ""):
        line["part_number"] = line.get("part")
    if line.get("cost") in (None, "") and line.get("unit_cost") not in (None, ""):
        line["cost"] = line.get("unit_cost")
    if line.get("ext_price") in (None, "") and line.get("extended_cost") not in (None, ""):
        line["ext_price"] = line.get("extended_cost")
    if line.get("mark") in (None, "") and line.get("door_mark") not in (None, ""):
        line["mark"] = line.get("door_mark")

    # Drop aliases once copied — they are not PricedLine fields.
    for alias in ("unit_cost", "extended_cost", "part"):
        line.pop(alias, None)

    for key, label in _PRICED_STRAY_LABELS.items():
        if key not in line:
            continue
        value = line.pop(key)
        if value is None or value == "":
            continue
        notes = _append_note(notes if isinstance(notes, str) else None, label, value)

    stray: list[str] = []
    for key in list(line.keys()):
        if key in _PRICED_LINE_FIELDS:
            continue
        value = line.pop(key)
        if value is None or value == "":
            continue
        stray.append(f"{key}={value}")
    if stray:
        notes = _append_note(
            notes if isinstance(notes, str) else None, "Extra", "; ".join(stray)
        )

    if notes is not None:
        line["notes"] = notes
    if "flags" in line:
        line["flags"] = coerce_flag_strings(line.get("flags"))
    return line


def normalize_priced_quote_payload(raw: Any) -> Any:
    """Map line_items→lines and close each row to the PricedLine allowlist."""
    if isinstance(raw, list):
        return [normalize_priced_line(item) if isinstance(item, dict) else item for item in raw]
    if not isinstance(raw, dict):
        return raw
    data = dict(raw)
    alt = data.pop("line_items", None)
    if isinstance(alt, list) and not isinstance(data.get("lines"), list):
        data["lines"] = alt
    elif isinstance(alt, list) and not data.get("lines"):
        data["lines"] = alt

    rows = data.get("lines")
    if isinstance(rows, list):
        data["lines"] = [
            normalize_priced_line(item) if isinstance(item, dict) else item for item in rows
        ]
    return data


def normalize_artifact_text(rel_path: str, content: str) -> str:
    """Return content, possibly rewritten, for known checkpoint paths."""
    key = rel_path.replace("\\", "/").lstrip("/")
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return content
    if key == "extracted/line_items.json":
        normalized = normalize_line_items_payload(data)
    elif key == "extracted/div10_takeoff.json":
        normalized = normalize_div10_takeoff_payload(data)
    elif key == "priced/line_items.json":
        normalized = normalize_priced_quote_payload(data)
    elif key == "extracted/hardware_sets.json":
        normalized = normalize_hardware_sets_payload(data)
    else:
        return content
    if normalized == data:
        return content
    return json.dumps(normalized, indent=2, ensure_ascii=False) + "\n"


def normalize_hardware_sets_payload(raw: Any) -> Any:
    """Apply manufacturer OCR aliases on hardware set items."""
    from cbc.modules.extraction.api.manufacturer_aliases import apply_to_hardware_item

    if not isinstance(raw, dict):
        return raw
    data = dict(raw)
    groups = data.get("hardware_sets")
    if not isinstance(groups, list):
        return data
    new_groups = []
    for group in groups:
        if not isinstance(group, dict):
            new_groups.append(group)
            continue
        g = dict(group)
        items = g.get("items")
        if isinstance(items, list):
            g["items"] = [
                apply_to_hardware_item(item) if isinstance(item, dict) else item
                for item in items
            ]
        new_groups.append(g)
    data["hardware_sets"] = new_groups
    return data
