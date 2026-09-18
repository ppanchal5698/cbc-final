"""Import FRP / Div 10 specialty take-off artifacts into the `takeoffs` collection.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from cbc.modules.extraction.infrastructure.collections import takeoffs
from cbc.shared import storage
from cbc.shared.pass_files import read_json


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def import_specialty_takeoffs(
    project: dict[str, Any], *, job: dict[str, Any] | None = None
) -> dict[str, int]:
    """Replace prior specialty rows for this bid with the latest artifact contents."""
    if job is not None:
        from cbc.modules.ops.api.jobs import holds_lease

        if not await holds_lease(job):
            return {"frp": 0, "div10": 0, "aborted": True}

    slug, project_id = project["slug"], project["_id"]
    coll = takeoffs()
    await coll.delete_many(
        {
            "bidRequestId": project_id,
            "takeoffType": {"$in": ["frp", "frpArea", "accessoryCount", "div10"]},
        }
    )

    frp_count = 0
    div10_count = 0
    root = storage.project_dir(slug)

    frp = read_json(root / "extracted" / "frp_takeoff.json")
    if isinstance(frp, dict):
        areas = frp.get("areas") if isinstance(frp.get("areas"), list) else []
        if not areas and frp.get("status"):
            areas = [{}]
        for area in areas:
            if not isinstance(area, dict):
                continue
            doc = {
                "bidRequestId": project_id,
                "projectId": project_id,
                "takeoffType": "frpArea",
                "method": "manual",
                "conversionMethod": "manual",
                "perimeterLf": area.get("perimeter_lf"),
                "insideCorners": area.get("inside_corners"),
                "outsideCorners": area.get("outside_corners"),
                "wallHeightFt": area.get("wall_height_ft"),
                "drawingScale": area.get("drawing_scale") or frp.get("drawing_scale"),
                "productType": area.get("product_type") or frp.get("product_type"),
                "manufacturer": area.get("manufacturer") or frp.get("manufacturer"),
                "location": area.get("location") or area.get("room"),
                "panelRequirements": area.get("panel_requirements")
                or frp.get("panel_requirements"),
                "trimRequirements": area.get("trim_requirements")
                or frp.get("trim_requirements"),
                "adhesiveRequirements": area.get("adhesive_requirements")
                or frp.get("adhesive_requirements"),
                "specialConditions": area.get("special_conditions")
                or frp.get("special_conditions"),
                "vu360Notes": area.get("vu360_notes")
                or area.get("geometry_notes")
                or frp.get("vu360_notes")
                or frp.get("geometry_notes"),
                "quantities": frp.get("quantities"),
                "constantsUsed": None,
                "status": frp.get("status") or "pendingConstants",
                "flags": list(frp.get("flags") or []) + list(area.get("flags") or []),
                "notes": area.get("geometry_notes") or frp.get("geometry_notes"),
                "sourceRef": {
                    "sourcePage": area.get("source_page"),
                    "sourceFile": area.get("source_file"),
                },
                "createdAt": _now(),
                "updatedAt": _now(),
            }
            await coll.insert_one(doc)
            frp_count += 1

    div10 = read_json(root / "extracted" / "div10_takeoff.json")
    if isinstance(div10, dict):
        items = div10.get("items") if isinstance(div10.get("items"), list) else []
        # Mirror FRP: empty items + status still surfaces a placeholder row so the
        # specialties panel is not silently empty when Div 10 is in scope.
        if not items and (div10.get("status") or div10.get("div10_in_scope")):
            items = [{}]
        for item in items:
            if not isinstance(item, dict):
                continue
            qty = item.get("qty")
            if qty is None:
                qty = item.get("quantity")
            doc = {
                "bidRequestId": project_id,
                "projectId": project_id,
                "takeoffType": "accessoryCount",
                "method": "manual",
                "conversionMethod": "manual",
                "productType": item.get("product_type") or item.get("description"),
                "manufacturer": item.get("manufacturer"),
                "location": item.get("location") or item.get("room"),
                "drawingRef": item.get("drawing_ref"),
                "qty": qty,
                "unit": item.get("unit"),
                "specifiedModel": item.get("specified_model") or item.get("model_series"),
                "finish": item.get("finish"),
                "alternate": item.get("alternate"),
                "quantities": {"count": qty} if qty is not None else None,
                "status": div10.get("status")
                or ("notExtracted" if not item else "measured"),
                "flags": list(div10.get("flags") or []) + list(item.get("flags") or []),
                "notes": item.get("notes"),
                "sourceRef": {
                    "sourcePage": item.get("source_page"),
                    "sourceFile": item.get("source_file"),
                    "evidenceNote": item.get("evidence_note"),
                },
                "createdAt": _now(),
                "updatedAt": _now(),
            }
            await coll.insert_one(doc)
            div10_count += 1

    return {"frp": frp_count, "div10": div10_count}
