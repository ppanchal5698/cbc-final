"""What the extract job asks the model: only what the parsers cannot read off a sheet.

Each reader runs after the take-off has been seeded in code, asks one narrow
question at a time (`domain/questions`), and writes an answer only where the
take-off has nothing - never over a value a sheet printed - with a flag for the
estimator to confirm. The first question that goes unanswered ends that reader's
asking: the provider is down or will not answer, and the rest stay the
estimator's. No answer ever fails the job.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from cbc.modules.extraction.domain import scope_rules
from cbc.modules.extraction.domain.questions import (
    FIND_SCHEDULE_TABLES,
    READ_DOOR_HANDING,
    READ_DOOR_SCHEDULE,
    READ_HARDWARE_SET,
    READ_TITLE_BLOCK,
)
from cbc.modules.extraction.infrastructure import pretakeoff, sheetmap, visual_pages
from cbc.modules.ops.api import ai as ops_ai
from cbc.shared import pdfpages, storage
from cbc.shared.pass_files import read_json, write_json

log = logging.getLogger("cbc.worker")

READ_BY_MODEL = "read_by_model"


def _extracted(slug: str) -> Path:
    return storage.project_dir(slug) / "extracted"


# ── the title block ──────────────────────────────────────────────────────────

TITLE_FIELDS = ("project_name", "brand", "address", "city", "state", "architect", "gc", "project_number")


async def title_block(slug: str) -> int:
    """The project fields the Ops-Hub record did not carry, read off the first sheet:
    its picture and its text layer, each field with the words it was read from. Only
    a field still null is written; the bid takes it only where the estimator left
    the field empty (`import_scope_metadata`)."""
    root = _extracted(slug)
    meta = read_json(root / "scope_metadata.json")
    sheets = read_json(sheetmap.sheetmap_path(slug))
    if not isinstance(meta, dict) or not isinstance(sheets, dict) or not sheets.get("files"):
        return 0
    missing = [field for field in TITLE_FIELDS if meta.get(field) in (None, "")]
    if not missing:
        return 0
    first = str(sheets["files"][0].get("path") or "")
    pdf = pretakeoff._resolve(slug, first)
    if pdf is None:
        return 0
    try:
        image = await asyncio.to_thread(pdfpages.page_image, pdf, 1, 200, root / "_ai_crops")
        text = (await asyncio.to_thread(pdfpages.page_text, pdf, 1)).strip()[:6000]
        prompt = "Fields wanted: " + ", ".join(missing)
        if text:
            prompt += "\n\nThe sheet's text layer, which may be out of reading order:\n" + text
        reply = await ops_ai.ask(READ_TITLE_BLOCK, prompt, images=[Path(image["image_path"])])
    except Exception as exc:  # no provider, no picture: the fields stay as they were
        log.warning("read_title_block not asked for %s: %s", slug, exc)
        return 0
    if reply.answer is None:
        return 0
    read = [field for field in missing if (getattr(reply.answer, field).value or "").strip()]
    for field in read:
        printed = getattr(reply.answer, field)
        meta[field] = printed.value.strip()
        meta.setdefault("field_sources", {})[field] = {
            "source_file": first, "source_page": 1, "excerpt": printed.excerpt, "read_by": "model",
        }
    if read:
        meta["flags"] = [flag for flag in meta.get("flags") or []
                         if not any(str(flag).startswith(f"title_block_not_read - {field} ") for field in read)]
        await asyncio.to_thread(write_json, root / "scope_metadata.json", meta)
    return len(read)


# ── handing, off the floor plan ──────────────────────────────────────────────

HANDINGS = ("LH", "RH", "LHR", "RHR")


async def handing(slug: str) -> int:
    """The handing the schedule did not give, read off the floor plan: a picture of
    each crop `visual_pages.handing_regions` chose - the fewest that show every such
    door - and the answer written only where the row has none, flagged
    `handing_read_from_plan`."""
    regions = await asyncio.to_thread(visual_pages.handing_regions, slug)
    if not regions:
        return 0
    path = _extracted(slug) / "line_items.json"
    payload = read_json(path)
    rows = payload.get("openings") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return 0
    open_rows = {
        str(row.get("door_number") or row.get("mark") or "").strip(): row
        for row in rows
        if isinstance(row, dict) and not row.get("handing")
    }
    filled = 0
    for region in regions:
        pdf = pretakeoff._resolve(slug, str(region["path"]))
        if pdf is None:
            continue
        try:
            image = await asyncio.to_thread(
                pdfpages.page_image, pdf, int(region["page"]), 300, path.parent / "_ai_crops", region["region"]
            )
            reply = await ops_ai.ask(READ_DOOR_HANDING, "Door marks: " + ", ".join(region["marks"]),
                                     images=[Path(image["image_path"])])
        except Exception as exc:  # no provider, no picture: the rows stay as they are
            log.warning("read_door_handing not asked for %s: %s", slug, exc)
            break
        if reply.answer is None:
            break
        for door in reply.answer.doors:
            row = open_rows.get(door.mark.strip())
            if row is None or door.handing not in HANDINGS or row.get("handing"):
                continue
            row["handing"] = door.handing
            row["flags"] = [*(row.get("flags") or []), "handing_read_from_plan"]
            row["handing_reason"] = door.reason
            filled += 1
    if filled:
        await asyncio.to_thread(write_json, path, payload)
    return filled


# ── schedules on a sheet with no text layer ──────────────────────────────────

# A set's scanned or outlined sheets that might hold its schedule. Waxahachie's
# door schedule and legend were on the 13th of 13.
MAX_PICTURED_SHEETS = 16
_PAD = 0.015  # of the sheet, round a table's box: the model's boxes are approximate
_SCHEDULE_ROLES = {"door_schedule", "door_schedule_candidate", "hardware"}


def _region(box: list[float], size: dict[str, Any]) -> list[float]:
    """A box in fractions of the picture, as a region of the page in points."""
    width, height = float(size["width"]), float(size["height"])
    x0, y0, x1, y1 = (max(0.0, box[0] - _PAD), max(0.0, box[1] - _PAD),
                      min(1.0, box[2] + _PAD), min(1.0, box[3] + _PAD))
    return [round(x0 * width, 2), round(y0 * height, 2), round(x1 * width, 2), round(y1 * height, 2)]


def _pictured_sheets(slug: str) -> list[tuple[str, int]]:
    """Schedule candidates with no text to parse - the ones only a picture can read."""
    sheets = read_json(sheetmap.sheetmap_path(slug))
    if not isinstance(sheets, dict):
        return []
    return [
        (str(entry.get("path") or ""), int(page["source_page"]))
        for entry in sheets.get("files") or []
        for page in entry.get("pages") or []
        if page.get("needs_visual_read") and _SCHEDULE_ROLES & set(page.get("roles") or [])
    ][:MAX_PICTURED_SHEETS]


def _opening(row: Any, path: str, page: int, size: dict[str, Any], region: list[float]) -> dict[str, Any]:
    values = row.model_dump()
    return {
        "door_number": row.door_number.strip(),
        **{key: values[key] for key in ("width", "height", "door_type", "door_material", "frame_type",
                                        "frame_material", "fire_rating", "hardware_set", "room_name")},
        "notes": row.remarks,
        "raw_row": " | ".join(str(v) for v in values.values() if v),
        "source_file": path, "source_page": page,
        "page_size": {"width": size["width"], "height": size["height"]}, "bbox": region,
        "confidence": 0.5, "flags": [READ_BY_MODEL],
        "evidence_note": "read off a picture of the sheet by the model; the box is the table's",
    }


def _hardware_set(answer: Any, path: str, page: int, size: dict[str, Any], region: list[float]) -> dict[str, Any]:
    name = answer.set_id.strip()
    return {
        "set_id": name, "hardware_set": name, "specified": answer.name,
        "source_file": path, "source_page": page,
        "page_size": {"width": size["width"], "height": size["height"]}, "bbox": region,
        "items": [{**item.model_dump(), "flags": [READ_BY_MODEL]} for item in answer.items],
        "flags": [READ_BY_MODEL],
    }


async def schedules(slug: str) -> dict[str, int]:
    """A door schedule and a hardware legend the parsers found no text for - a scan,
    or a sheet whose letters are outlines - read off pictures of the sheets: first
    where on each sheet the tables are, then what each table says, at a size it can
    be read. Only what the take-off has none of is asked for; every row carries its
    page, its table's box and `read_by_model`."""
    root = _extracted(slug)
    doors_file = read_json(root / "line_items.json")
    sets_file = read_json(root / "hardware_sets.json")
    need_doors = not (isinstance(doors_file, dict) and doors_file.get("openings"))
    need_sets = not (isinstance(sets_file, dict) and any(isinstance(v, list) and v for v in sets_file.values()))
    if not (need_doors or need_sets):
        return {}
    doors: list[dict[str, Any]] = []
    sets: list[dict[str, Any]] = []
    crops = root / "_ai_crops"
    try:
        for path, page in _pictured_sheets(slug):
            pdf = pretakeoff._resolve(slug, path)
            if pdf is None:
                continue
            size = await asyncio.to_thread(pdfpages.page_size, pdf, page)
            sheet = await asyncio.to_thread(pdfpages.page_image, pdf, page, 200, crops)
            found = await ops_ai.ask(FIND_SCHEDULE_TABLES, "Find the door schedule and hardware set tables.",
                                     images=[Path(sheet["image_path"])])
            if found.answer is None:
                break
            for table in found.answer.tables:
                wanted = need_doors if table.kind == "door_schedule" else need_sets
                if not wanted:
                    continue
                region = _region(table.box, size)
                # ponytail: one picture per table - legible to ~700pt across; tile a
                # bigger schedule into bands when a bid's outgrows one image.
                crop = await asyncio.to_thread(pdfpages.page_image, pdf, page, 300, crops, region)
                question = READ_DOOR_SCHEDULE if table.kind == "door_schedule" else READ_HARDWARE_SET
                reply = await ops_ai.ask(question, f"Table: {table.title or table.kind}", images=[Path(crop["image_path"])])
                if reply.answer is None:
                    continue
                if table.kind == "door_schedule":
                    doors += [_opening(row, path, page, size, region) for row in reply.answer.rows]
                else:
                    sets.append(_hardware_set(reply.answer, path, page, size, region))
    except Exception as exc:  # no provider, no picture: what was read so far still lands
        log.warning("schedule tables not read for %s: %s", slug, exc)
    if doors:
        scope_rules.apply_to(doors)
        await asyncio.to_thread(write_json, root / "line_items.json", {
            "source": "read off pictures of the sheets by the model (read_door_schedule)",
            "source_file": doors[0]["source_file"], "source_page": doors[0]["source_page"], "openings": doors,
        })
    if sets:
        await asyncio.to_thread(write_json, root / "hardware_sets.json", {
            "source": "read off pictures of the sheets by the model (read_hardware_set)", "sets": sets,
        })
    return {"doors": len(doors), "sets": len(sets)}
