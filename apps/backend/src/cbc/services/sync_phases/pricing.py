"""Openings, written down for the pricing pass to read.

Exports carry the estimator's confirmed state back down to disk so the next pass
reconciles against it rather than overwriting it. The priced lines that come
back, and the approved quote written down for the proposal, are quoting's
(cbc.modules.quoting.api.priced_lines).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from cbc.modules.extraction.api import openings as extraction_openings
from cbc.services import storage
from cbc.services.sync_phases._common import _now, _write_json


async def export_line_items(project: dict[str, Any]) -> Path:
    """Write the estimator-confirmed state down for Claude's next phase."""
    slug, project_id = project["slug"], project["_id"]
    openings = []
    for doc in await extraction_openings.list_for_project(project_id, sort=[("mark", 1)]):
        if doc.get("status") == "duplicate" and doc.get("duplicateOf"):
            continue
        evidence = doc.get("evidence") or {}
        openings.append(
            {
                "mark": doc.get("mark"),
                "door_number": doc.get("mark"),
                "description": doc.get("description"),
                "size": doc.get("size"),
                "qty": doc.get("qty", 1),
                "hardware_set": doc.get("hwSet"),
                "division": doc.get("division"),
                "handing": doc.get("handing"),
                "finish": doc.get("finish"),
                "fire_rating": doc.get("fireRating"),
                "frame_type": doc.get("frameType"),
                "wall_type": doc.get("wallType"),
                "frame_depth": doc.get("frameDepth"),
                "alternate": doc.get("alternateGroup"),
                "source_file": evidence.get("sourceFile"),
                "source_page": evidence.get("sourcePage"),
                "bbox": evidence.get("bbox"),
                "page_size": evidence.get("pageSize"),
                "confidence": doc.get("confidence"),
                "flags": doc.get("flags", []),
                "status": doc.get("status"),
                "confirmed_by": doc.get("confirmedBy"),
                "added_by_hand": doc.get("addedByHand", False),
            }
        )

    path = storage.project_dir(slug) / "extracted" / "door_schedule.json"
    payload = {
        "project": slug,
        "project_code": project.get("code"),
        "exported_at": _now().isoformat(),
        "source": "estimator-confirmed via Ops-Hub",
        "openings": openings,
    }
    await asyncio.to_thread(_write_json, path, payload)
    return path
