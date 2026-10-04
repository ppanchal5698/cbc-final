"""Import FRP / Div 10 specialty take-offs as line items.

These used to land in their own `takeoffs` collection and be read again, as raw
artifacts, by the pricing pass. Two stores for one item is how an accessory gets
quoted twice, and it also meant the review screen needed a second row component
that never quite lined up with the openings table beside it.

They are line items. The line-item path already expected them: `export_line_items`
carries `division`, `priced_lines._group_type` routes `10*` to the accessories
block and `06*` to the FRP block, and `pricing.DIVISION_BANDS` already prices
`10 21`, `10 28` and `06 64`. The specialty artifacts were the bolt-on, not the
line items.

So an accessory count and an FRP area now become openings with a division and a
`specialty` sub-document, and the pricing pass reads `line_items.json` alone.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import InsertOne, UpdateOne

from cbc.modules.extraction.api import openings as extraction_openings
from cbc.shared import storage
from cbc.shared.pass_files import read_json

# Spec sections, because that is what the rest of the system routes on:
# `priced_lines._group_type` groups by the division prefix and
# `pricing.DIVISION_BANDS` carries the margin band for each of these.
DIVISION_PARTITIONS = "10 21"
DIVISION_ACCESSORIES = "10 28"
DIVISION_FRP = "06 64"

# Product types that belong to the partitions band rather than accessories.
_PARTITION_WORDS = ("partition", "compartment", "urinal screen", "screen")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _division_for(product_type: str | None) -> str:
    text = (product_type or "").strip().lower()
    if any(word in text for word in _PARTITION_WORDS):
        return DIVISION_PARTITIONS
    return DIVISION_ACCESSORIES


def _evidence(row: dict[str, Any]) -> dict[str, Any]:
    """Provenance in the shape the sheet viewer already draws for an opening.

    `bbox` and `pageSize` are measured against the real page by
    `geometry.measure_specialty_bboxes`, never written by the pass. A row that
    could not be pinned to one printed line arrives with `bbox: None` and a
    `bbox_*` flag - visible as a page number with no highlight, rather than a
    rectangle nobody measured.
    """
    return {
        "note": row.get("evidence_note") or row.get("bbox_note"),
        "sourceFile": row.get("source_file"),
        "sourcePage": row.get("source_page"),
        "bbox": row.get("bbox"),
        "pageSize": row.get("page_size"),
        "cellBoxes": row.get("cell_boxes"),
    }


def _flags(row: dict[str, Any], payload: dict[str, Any], *, placeholder: bool) -> list[str]:
    """Row flags, plus the artifact's own only where they belong to no row.

    The artifact carries flags about the pass as a whole - "div10 mentions need
    review", "no toilet partition manufacturer found on assigned pages". Copying
    those onto every item repeated the same three chips down the table and
    buried the flag that was actually about that line. They go on the
    placeholder, which is the row that stands for the take-off itself.
    """
    flags = list(row.get("flags") or [])
    if placeholder:
        flags = list(payload.get("flags") or []) + flags
    return flags


def _div10_fields(
    item: dict[str, Any], payload: dict[str, Any], *, placeholder: bool = False
) -> dict[str, Any]:
    qty = item.get("qty")
    if qty is None:
        qty = item.get("quantity")
    product_type = item.get("product_type") or item.get("description")
    description = " — ".join(
        part for part in (
            product_type or "accessory",
            item.get("manufacturer"),
            item.get("location") or item.get("room"),
        ) if part
    )
    return {
        "mark": item.get("specified_model") or item.get("model_series") or None,
        "description": description,
        "division": _division_for(product_type),
        "qty": qty,
        "manufacturer": item.get("manufacturer"),
        "finish": item.get("finish"),
        "location": item.get("location") or item.get("room"),
        "notes": item.get("notes"),
        "alternateGroup": item.get("alternate"),
        "evidence": _evidence(item),
        "flags": _flags(item, payload, placeholder=placeholder),
        "specialty": {
            "kind": "div10",
            "status": payload.get("status"),
            "productType": product_type,
            "specifiedModel": item.get("specified_model") or item.get("model_series"),
            "unit": item.get("unit"),
            "drawingRef": item.get("drawing_ref"),
            "room": item.get("room"),
        },
    }


def _frp_fields(
    area: dict[str, Any], payload: dict[str, Any], *, placeholder: bool = False
) -> dict[str, Any]:
    location = area.get("location") or area.get("room")
    description = " — ".join(
        part for part in (
            location or area.get("product_type") or "FRP area",
            area.get("manufacturer") or payload.get("manufacturer"),
        ) if part
    )
    return {
        # No mark: an FRP area is not a numbered opening, and inventing one
        # would sort it in among the doors.
        "mark": None,
        "description": description,
        "division": DIVISION_FRP,
        # Deliberately null. The geometry is measured, the conversion to panels
        # is not - the FRP constants are still an open item, and a quantity
        # invented here would be priced as if it were measured.
        "qty": None,
        "manufacturer": area.get("manufacturer") or payload.get("manufacturer"),
        "location": location,
        "notes": area.get("geometry_notes") or payload.get("geometry_notes"),
        "evidence": _evidence(area),
        "flags": _flags(area, payload, placeholder=placeholder),
        "specialty": {
            "kind": "frp",
            "productType": area.get("product_type") or payload.get("product_type"),
            "perimeterLf": area.get("perimeter_lf"),
            "insideCorners": area.get("inside_corners"),
            "outsideCorners": area.get("outside_corners"),
            "wallHeightFt": area.get("wall_height_ft"),
            "drawingScale": area.get("drawing_scale") or payload.get("drawing_scale"),
            "panelRequirements": area.get("panel_requirements")
            or payload.get("panel_requirements"),
            "trimRequirements": area.get("trim_requirements")
            or payload.get("trim_requirements"),
            "adhesiveRequirements": area.get("adhesive_requirements")
            or payload.get("adhesive_requirements"),
            "specialConditions": area.get("special_conditions")
            or payload.get("special_conditions"),
            "status": payload.get("status"),
        },
    }


def _key(fields: dict[str, Any], seen: dict[str, int]) -> str:
    """Identify the same specialty row from one extraction to the next.

    Page plus model is stable across runs. Two rows can still share it - the
    first real bid set carries two `KAY 3741` soap dispensers on page 21 - so an
    ordinal separates them by the order the pass emitted them, which is the only
    thing available and is stable in practice.
    """
    specialty = fields.get("specialty") or {}
    evidence = fields.get("evidence") or {}
    base = "|".join(
        str(part) for part in (
            "specialty",
            specialty.get("kind"),
            evidence.get("sourcePage"),
            fields.get("mark") or specialty.get("productType") or fields.get("location"),
        )
    )
    seen[base] = seen.get(base, 0) + 1
    return f"{base}|{seen[base]}"


def _status_for(fields: dict[str, Any]) -> str:
    return "needs_look" if fields.get("flags") else "clear"


async def import_specialty_takeoffs(
    project: dict[str, Any], *, job: dict[str, Any] | None = None
) -> dict[str, int]:
    """Load the specialty artifacts into `openings`, beside the door openings."""
    if job is not None:
        from cbc.modules.ops.api.jobs import holds_lease

        if not await holds_lease(job):
            return {"frp": 0, "div10": 0, "aborted": True}

    slug, project_id = project["slug"], project["_id"]
    root = storage.project_dir(slug)

    rows: list[dict[str, Any]] = []

    div10 = read_json(root / "extracted" / "div10_takeoff.json")
    if isinstance(div10, dict):
        items = [item for item in (div10.get("items") or []) if isinstance(item, dict)]
        # In scope and nothing found is a result, not an absence. It used to be a
        # placeholder row in the specialties panel; now it is a flagged line in
        # the table, which is where the estimator is already looking and which
        # puts it under "needs a look" rather than nowhere.
        placeholder = not items and bool(div10.get("status") or div10.get("div10_in_scope"))
        for item in items or ([{}] if placeholder else []):
            rows.append(_div10_fields(item, div10, placeholder=placeholder))

    frp = read_json(root / "extracted" / "frp_takeoff.json")
    if isinstance(frp, dict):
        areas = [area for area in (frp.get("areas") or []) if isinstance(area, dict)]
        placeholder = not areas and bool(frp.get("status") or frp.get("frp_in_scope"))
        for area in areas or ([{}] if placeholder else []):
            rows.append(_frp_fields(area, frp, placeholder=placeholder))

    seen: dict[str, int] = {}
    keyed = [(_key(fields, seen), fields) for fields in rows]

    # Everything this importer owns, so a row the pass stopped extracting is not
    # left behind as a phantom line. Estimator-owned rows are handled below.
    existing_docs = await extraction_openings.list_for_project(project_id)
    existing = {
        doc.get("specialtyKey"): doc
        for doc in existing_docs
        if doc.get("specialtyKey")
    }

    bulk: list[InsertOne | UpdateOne] = []
    counts = {"div10": 0, "frp": 0}
    for key, fields in keyed:
        kind = (fields.get("specialty") or {}).get("kind")
        counts[kind] = counts.get(kind, 0) + 1
        current = existing.pop(key, None)
        if current is None:
            bulk.append(
                InsertOne({
                    "projectId": project_id,
                    "bidRequestId": project_id,
                    "specialtyKey": key,
                    "status": _status_for(fields),
                    "addedByHand": False,
                    "createdAt": _now(),
                    "updatedAt": _now(),
                    **fields,
                })
            )
        elif current.get("confirmedAt") or current.get("addedByHand") or current.get("edits"):
            # The pass replaces what it extracted and never what a person
            # decided; only the measured evidence is refreshed, because a bbox
            # is measured from the sheet each run and cannot be typed anyway.
            bulk.append(
                UpdateOne(
                    {"_id": current["_id"]},
                    {"$set": {"evidence": fields["evidence"], "updatedAt": _now()}},
                )
            )
        else:
            bulk.append(
                UpdateOne(
                    {"_id": current["_id"]},
                    {"$set": {"status": _status_for(fields), "updatedAt": _now(), **fields}},
                )
            )

    # Rows this importer wrote on an earlier run that the pass no longer emits.
    for stale in existing.values():
        if stale.get("confirmedAt") or stale.get("addedByHand") or stale.get("edits"):
            continue
        bulk.append(UpdateOne({"_id": stale["_id"]}, {"$set": {"status": "duplicate"}}))

    if bulk:
        if job is not None:
            from cbc.modules.ops.api.jobs import holds_lease

            if not await holds_lease(job):
                return {"frp": 0, "div10": 0, "aborted": True}
        await extraction_openings.apply_bulk(bulk)

    return {"frp": counts.get("frp", 0), "div10": counts.get("div10", 0)}
