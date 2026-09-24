"""Measurements taken from the sheet rather than asked of the model.

A pass told a bbox was required invented six, then wrote six nulls. The
rows are on the page, so they are measured here instead.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from cbc.modules.extraction.domain.schedule import _normalize_schedule_payload, door_number
from cbc.shared import storage
from cbc.shared.pass_files import read_json, write_json

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
    path = directory / "extracted" / "line_items.json"
    payload = read_json(path)
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

    from cbc.shared.pdfrows import attach_measured_bboxes, detect_shift

    by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for opening in openings:
        page_number = opening.get("source_page")
        # Always remasure. Agent-written boxes have been arithmetic inventions
        # (identical width, exact vertical steps); keeping any existing bbox
        # would leave those wrong highlights on the review sheet.
        if isinstance(page_number, int):
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
            # Drop any agent-invented box rather than leave a wrong highlight.
            opening["bbox"] = None
            opening.pop("cell_boxes", None)
            flags = opening.setdefault("flags", [])
            if isinstance(flags, list) and "bbox_unavailable" not in flags:
                flags.append("bbox_unavailable")
            opening["bbox_note"] = why

    attached = unmatched = 0
    touched = False
    for page_number, group in by_page.items():
        named = next((o.get("source_file") for o in group if o.get("source_file")), None)
        if named:
            candidates = [p for p in pdfs if Path(named).name == p.name]
        elif len(pdfs) == 1:
            candidates = list(pdfs)
        else:
            candidates = []
        if len(candidates) != 1:
            if named:
                why = (
                    f"source_file {named!r} matches none of the uploads"
                    if not candidates
                    else f"source_file {named!r} matches {len(candidates)} of {len(pdfs)} uploads"
                )
            else:
                why = f"no source_file and {len(pdfs)} PDF(s) in uploads/raw"
            _give_up(group, page_number, why)
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
                group,
                document[page_number - 1],
                shift=shift,
                overwrite=True,
            )
            attached += got
            unmatched += missed
            # Persist the file we measured against so a later export keeps it.
            for opening in group:
                if opening.get("bbox") and not opening.get("source_file"):
                    opening["source_file"] = candidates[0].name
        finally:
            document.close()

    if attached or unmatched or touched:
        # Written back in the shape it arrived in, so a run that wrote a bare
        # array or a `lines` wrapper still recognises its own file.
        if isinstance(payload, list):
            write_json(path, openings)
        else:
            key = "openings" if "openings" in payload else "lines"
            write_json(path, {**payload, key: openings})
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
    from cbc.modules.pricing.api.reference_library import depth_for_wall_type

    slug = project["slug"]
    path = storage.project_dir(slug) / "extracted" / "line_items.json"
    payload = read_json(path)
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
            write_json(path, openings)
        else:
            key = "openings" if "openings" in payload else "lines"
            write_json(path, {**payload, key: openings})
    return derived, flagged


# Which artifact holds the rows, and where inside it the list lives.
_SPECIALTY_ARTIFACTS = (
    ("div10_takeoff.json", "items"),
    ("frp_takeoff.json", "areas"),
)


def measure_specialty_bboxes(project: dict[str, Any]) -> tuple[int, int]:
    """Give Div 10 and FRP rows the same measured evidence an opening gets.

    These rows were traceable only to a page number, which NFR-3 does not accept
    from an opening and should not have accepted from an accessory either: a page
    number names a sheet the estimator still has to search by eye. They are read
    off a printed schedule exactly like a door row is, so the row can be found
    again and measured.

    Nothing here invents. On the first real bid set this measures 4 of 10 Div 10
    items and flags the other 6 with a reason - three of which turned out to cite
    a page their model does not appear on at all. That is the feature working: an
    item that cannot be pinned to one row is a provenance problem worth seeing,
    not one worth papering over with a plausible rectangle.

    FRP areas mostly have no row to find - "Kitchen / back-of-house, 13 interior
    elevation views" is derived from elevations, not copied off a line of text -
    so they are measured on the same terms and usually come back flagged.

    Returns (attached, unmatched) across both artifacts.
    """
    slug = project["slug"]
    directory = storage.project_dir(slug)
    raw = directory / "uploads" / "raw"
    pdfs = sorted(raw.glob("*.pdf")) if raw.is_dir() else []
    if not pdfs:
        return 0, 0

    import fitz

    from cbc.shared.pdfrows import attach_specialty_bboxes, detect_shift

    attached = unmatched = 0

    for filename, key in _SPECIALTY_ARTIFACTS:
        path = directory / "extracted" / filename
        payload = read_json(path)
        if not isinstance(payload, dict):
            continue
        rows = payload.get(key)
        if not isinstance(rows, list) or not rows:
            continue

        by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            if not isinstance(row, dict):
                continue
            page_number = row.get("source_page")
            if isinstance(page_number, float) and page_number.is_integer():
                page_number = int(page_number)
            if isinstance(page_number, int):
                by_page[page_number].append(row)
            else:
                # No page means nothing to measure against. Say so on the record
                # rather than leaving a silent null.
                row["bbox"] = None
                flags = row.setdefault("flags", [])
                if isinstance(flags, list) and "bbox_unavailable" not in flags:
                    flags.append("bbox_unavailable")
                row["bbox_note"] = "no source_page"
                unmatched += 1

        touched = bool(by_page)
        for page_number, group in by_page.items():
            named = next((r.get("source_file") for r in group if r.get("source_file")), None)
            if named:
                candidates = [p for p in pdfs if Path(named).name == p.name]
            elif len(pdfs) == 1:
                candidates = list(pdfs)
            else:
                candidates = []
            if len(candidates) != 1:
                why = (
                    f"source_file {named!r} matches none of the uploads"
                    if named else f"no source_file and {len(pdfs)} PDF(s) in uploads/raw"
                )
                log.warning(
                    "specialty bbox: %s page %s left unmeasured (%s) - %d row(s)",
                    filename, page_number, why, len(group),
                )
                for row in group:
                    row["bbox"] = None
                    row.pop("cell_boxes", None)
                    flags = row.setdefault("flags", [])
                    if isinstance(flags, list) and "bbox_unavailable" not in flags:
                        flags.append("bbox_unavailable")
                    row["bbox_note"] = why
                    unmatched += 1
                continue

            try:
                document = fitz.open(candidates[0])
            except Exception as exc:  # noqa: BLE001 - any failure is "cannot measure"
                log.warning("specialty bbox: cannot open %s: %s", candidates[0].name, exc)
                for row in group:
                    row["bbox"] = None
                    flags = row.setdefault("flags", [])
                    if isinstance(flags, list) and "bbox_unavailable" not in flags:
                        flags.append("bbox_unavailable")
                    row["bbox_note"] = f"cannot open {candidates[0].name}: {exc}"
                    unmatched += 1
                continue
            try:
                if not 0 <= page_number - 1 < document.page_count:
                    for row in group:
                        row["bbox"] = None
                        flags = row.setdefault("flags", [])
                        if isinstance(flags, list) and "bbox_unavailable" not in flags:
                            flags.append("bbox_unavailable")
                        row["bbox_note"] = (
                            f"{candidates[0].name} has {document.page_count} page(s)"
                        )
                        unmatched += 1
                    continue
                shift = detect_shift(document, str(candidates[0]))
                got, missed = attach_specialty_bboxes(
                    group, document[page_number - 1], shift=shift, overwrite=True,
                )
                attached += got
                unmatched += missed
                for row in group:
                    if row.get("bbox") and not row.get("source_file"):
                        row["source_file"] = candidates[0].name
            finally:
                document.close()

        if touched or any(r.get("bbox_note") for r in rows if isinstance(r, dict)):
            write_json(path, {**payload, key: rows})

    return attached, unmatched
