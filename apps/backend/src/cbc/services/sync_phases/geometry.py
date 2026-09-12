"""Measurements taken from the sheet rather than asked of the model.

A pass told a bbox was required invented six, then wrote six nulls. The
rows are on the page, so they are measured here instead.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from cbc.services import storage
from cbc.services.sync_phases._common import (
    _normalize_schedule_payload,
    _read_json,
    _write_json,
    door_number,
)

log = logging.getLogger("cbc.services.sync")


def measure_bboxes(project: dict[str, Any]) -> tuple[int, int]:
    """Give every opening the bbox of the row it was actually read from.

    Runs before validation, on what the extracting pass just wrote. The pass
    reads schedules through `extract_text`, which carries no coordinates, so by
    the time it builds an opening the geometry is gone - and asking it for the
    field anyway produced first six invented boxes, then six nulls.

    The rows are still on the page and the values are still in the opening, so
    the row can be found again and measured. Nothing here invents: an opening
    that does not match exactly one row keeps a null bbox and a flag.

    Returns (attached, unmatched).
    """
    slug = project["slug"]
    directory = storage.project_dir(slug)
    path = directory / "extracted" / "door_schedule.json"
    payload = _read_json(path)
    if payload is None:
        return 0, 0

    openings = _normalize_schedule_payload(payload)["openings"]
    if not openings:
        return 0, 0

    raw = directory / "uploads" / "raw"
    pdfs = sorted(raw.glob("*.pdf")) if raw.is_dir() else []
    if not pdfs:
        return 0, 0

    import fitz

    from cbc.core.pdfrows import attach_measured_bboxes, detect_shift

    by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for opening in openings:
        page_number = opening.get("source_page")
        if isinstance(page_number, int) and not opening.get("bbox"):
            by_page[page_number].append(opening)
    if not by_page:
        return 0, 0

    def _give_up(group: list[dict[str, Any]], page_number: int, why: str) -> None:
        """Say which openings lost their location, and why, on the record itself.

        Every branch below used to be a bare `continue`: an ambiguous filename, a
        PDF that would not open, a page number past the end of the document -
        each dropped a whole page of openings and reported the same clean
        "0 measured" as a project with no work to do. The estimator then saw
        rows with no highlight and nothing saying why.
        """
        marks = [door_number(o) or "?" for o in group]
        log.warning(
            "bbox: page %s left unmeasured (%s) - %d opening(s): %s",
            page_number, why, len(group), ", ".join(marks[:8]) + ("..." if len(marks) > 8 else ""),
        )
        for opening in group:
            flags = opening.setdefault("flags", [])
            if isinstance(flags, list) and "bbox_unavailable" not in flags:
                flags.append("bbox_unavailable")
            opening["bbox_note"] = why

    attached = unmatched = 0
    touched = False
    for page_number, group in by_page.items():
        named = next((o.get("source_file") for o in group if o.get("source_file")), None)
        candidates = [p for p in pdfs if named and Path(named).name == p.name]
        if not candidates:
            _give_up(group, page_number, f"source_file {named!r} matches none of the uploads")
            touched = True
            continue
        if len(candidates) != 1:
            _give_up(
                group, page_number,
                f"source_file {named!r} matches {len(candidates)} of {len(pdfs)} uploads",
            )
            touched = True
            continue
        try:
            document = fitz.open(candidates[0])
        except Exception as exc:
            _give_up(group, page_number, f"cannot open {candidates[0].name}: {exc}")
            touched = True
            continue
        try:
            if not 0 <= page_number - 1 < document.page_count:
                _give_up(
                    group, page_number,
                    f"{candidates[0].name} has {document.page_count} page(s)",
                )
                touched = True
                continue
            shift = detect_shift(document, str(candidates[0]))
            got, missed = attach_measured_bboxes(
                group, document[page_number - 1], shift=shift
            )
            attached += got
            unmatched += missed
        finally:
            document.close()

    if attached or touched:
        # Written back in the shape it arrived in, so a run that wrote a bare
        # array or a `lines` wrapper still recognises its own file.
        if isinstance(payload, list):
            _write_json(path, openings)
        else:
            key = "openings" if "openings" in payload else "lines"
            _write_json(path, {**payload, key: openings})
    return attached, unmatched
def derive_frame_depths(project: dict[str, Any]) -> tuple[int, int]:
    """Fill in each opening's frame throat from its wall construction.

    The depth is not on the drawing - it follows from the wall, which is why the
    process flow calls wall type "the thing that derives the frame depth" and why
    reference-library carries the five standard throats. The field was in the
    extraction schema and nothing ever populated it: neither of the two real bid
    sets produced a single frame_depth, and the table was reachable only through
    the settings screen.

    A lookup, not a guess. An opening whose wall type is missing or unrecognised
    keeps a null depth and is flagged, which is the table's own instruction: "Do
    NOT guess a depth. Flag the opening for estimator review." A frame ordered to
    the wrong throat does not fit, and that is found out on site.

    Returns (derived, flagged).
    """
    from cbc.services.reference_library import depth_for_wall_type

    slug = project["slug"]
    path = storage.project_dir(slug) / "extracted" / "door_schedule.json"
    payload = _read_json(path)
    if payload is None:
        return 0, 0
    openings = _normalize_schedule_payload(payload)["openings"]
    if not openings:
        return 0, 0

    derived = flagged = 0
    for opening in openings:
        if opening.get("frame_depth"):
            continue
        entry = depth_for_wall_type(opening.get("wall_type"))
        if entry:
            opening["frame_depth"] = entry.get("depth")
            opening["frame_depth_inches"] = entry.get("depth_inches")
            derived += 1
        else:
            flagged += 1
            flags = opening.setdefault("flags", [])
            note = (
                "wall_type_missing"
                if not opening.get("wall_type")
                else "wall_type_unrecognised"
            )
            if note not in flags:
                flags.append(note)

    if derived:
        if isinstance(payload, list):
            _write_json(path, openings)
        else:
            key = "openings" if "openings" in payload else "lines"
            _write_json(path, {**payload, key: openings})
    return derived, flagged
