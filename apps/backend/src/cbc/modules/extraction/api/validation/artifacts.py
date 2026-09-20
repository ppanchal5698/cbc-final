"""What a run must have written before its output is accepted.

These checks were in `scripts/validate_project.py`, which made the worker import
a script to find out whether a job had produced valid artifacts - `apps` reaching
sideways into `scripts/` for a rule that is neither a script's business nor the
application's. The rule is about the domain's own files, so it lives in the
domain, and `apps/backend/scripts/validate_project.py` is the command-line
front for it.

`check_extraction`, `check_pricing` and `check_proposal` each return
`(problems, warnings)`. Problems reject the job; warnings are reported and let it
through. `validate_job_artifacts` is the worker's gate and raises on problems.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


import fitz

from cbc.shared.paths import repo_root, storage_root
from cbc.modules.ops.api.artifact_gate import ArtifactValidationError
from cbc.modules.pricing.api.confidence import CONFIDENCE_FLOOR
from cbc.shared import pdfcheck
from cbc.shared.pdfrows import rows_from_words

ROOT = repo_root()

HARD_FIELDS = ("door_number", "source_page")
SOFT_FIELDS = ("handing", "finish", "fire_rating", "hardware_set")

PRICING_LINE_FIELDS = ("line_id", "group", "group_type", "quantity", "cost_source")
PRICING_GROUP_TYPES = frozenset({"door", "accessories", "frp", "other"})


# A citation that names a sheet somebody can open, rather than a vendor's name.
# "Price based on Pemko catalog" is not a citation; "pemko_markar_price_book_2026.pdf
# PDF p67" is - and it is exactly what find_pages hands back.
_CATALOG_FILE = re.compile(r"[\w.-]+\.(?:pdf|xlsx|xls)", re.IGNORECASE)
_BASELINE_CITATION = re.compile(r"catalog\.md", re.IGNORECASE)
_SPECIAL_NET_CITATION = re.compile(
    r"special[- ]?net|item[- ]?code|hager_special_nets|get_special_net",
    re.IGNORECASE,
)

# Cost paths a run can obtain on its own: P21, PDF list×multiplier, curated
# special-net sheet, or the markdown catalog.md baseline (Path 2b). Human-only
# labels (DISTRIBUTOR_MANUAL, VENDOR_RFQ, MANUAL) stay out.
_COST_SOURCES_A_RUN_CAN_READ = frozenset(
    {"P21_LAST_PO", "LIST_X_MULTIPLIER", "SPECIAL_NET", "CATALOG_BASELINE"}
)

_CLAIMS_APPROVAL = re.compile(r"(?:estimator|purchasing)[- ]?approved", re.IGNORECASE)
def _added_by_hand(row: dict) -> bool:
    """Did the estimator enter this line themselves, rather than a drawing produce it?

    The UI writes both markers when someone adds a line; either one is enough.
    """
    return bool(row.get("added_by_hand")) or str(row.get("status") or "").lower() == "by_hand"
def _valid_bbox(box: Any) -> bool:
    return (
        isinstance(box, list)
        and len(box) == 4
        and all(isinstance(v, (int, float)) for v in box)
        and box[2] > box[0]
        and box[3] > box[1]
    )


# How much of a claimed box has to sit on text the extractor actually found.
# Measured on a real fabrication: six invented boxes scored 0.001-0.179 against
# page 19 of the Baldwin set, while every real row and every real cell scores
# 1.000. Half is a wide margin either way.
BBOX_COVERAGE = 0.5
def _page_boxes(pdf_path: Path, page_number: int) -> tuple[list, tuple[float, float]] | None:
    """Every row and cell box the extractor finds on one page, in display space."""
    # Imported at module scope. These used to be imported here inside a bare
    # `except Exception: return None`, together with a sys.path hack needed only
    # while this code lived in scripts/ - so any import problem disabled the
    # whole bbox check and reported a clean pass. It is a hard dependency; if it
    # cannot be imported the run should say so, not quietly stop checking.
    try:
        document = fitz.open(pdf_path)
    except Exception:
        return None
    try:
        if not 0 <= page_number - 1 < document.page_count:
            return None
        page = document[page_number - 1]
        boxes = []
        for row in rows_from_words(page):
            boxes.append(fitz.Rect(row["bbox"]))
            boxes.extend(fitz.Rect(cell) for cell in row["cell_boxes"])
        return boxes, (page.rect.width, page.rect.height)
    finally:
        document.close()
def check_bboxes_are_real(project: str, openings: list[dict]) -> tuple[list[str], list[str]]:
    """Every bbox must land on text that is genuinely there.

    The estimator verifies extracted values by eye against a highlight on the
    real sheet, so a bbox is not decoration - it is the check itself. A run
    produced six boxes of identical width marching down the page in exact
    20-point steps: an arithmetic sequence, invented to satisfy a rule that only
    asked whether a bbox was well formed. Shape is not truth, and in a drawing
    as dense as a plan set an invented box still overlaps *something*, so
    "contains a word" does not separate them either.

    What does: a real box is one the extractor could have produced. Compare each
    claim against the rows and cells actually on that page.
    """
    problems: list[str] = []
    warnings: list[str] = []

    raw = storage_root() / project / "uploads" / "raw"
    pdfs = sorted(raw.glob("*.pdf")) if raw.is_dir() else []

    cache: dict[tuple[str, int], Any] = {}
    for index, opening in enumerate(openings, start=1):
        label = opening.get("door_number") or opening.get("mark") or f"opening {index}"
        box = opening.get("bbox")
        page_number = opening.get("source_page")
        if not _valid_bbox(box) or not isinstance(page_number, int):
            continue  # already reported by the shape checks

        named = opening.get("source_file")
        candidates = [p for p in pdfs if named and Path(named).name == p.name] or pdfs
        if len(candidates) != 1:
            warnings.append(
                f"{project}: opening {label} cannot be checked against its sheet - "
                f"{'no source_file and ' if not named else ''}"
                f"{len(pdfs)} PDF(s) in uploads/raw"
            )
            continue
        pdf = candidates[0]

        key = (pdf.name, page_number)
        if key not in cache:
            cache[key] = _page_boxes(pdf, page_number)
        found = cache[key]
        if found is None:
            warnings.append(f"{project}: could not read {pdf.name} page {page_number} to check bboxes")
            continue
        boxes, (width, height) = found

        size = opening.get("page_size") or {}
        if isinstance(size, dict) and size.get("width") and size.get("height"):
            if abs(size["width"] - width) > 1 or abs(size["height"] - height) > 1:
                problems.append(
                    f"{project}: opening {label} records page_size "
                    f"{size['width']}x{size['height']} but page {page_number} of "
                    f"{pdf.name} is {width:g}x{height:g}. A bbox scaled against the "
                    "wrong frame lands nowhere near its row"
                )

        claim = fitz.Rect(box)
        area = claim.get_area()
        covered = max(
            ((claim & other).get_area() / area if area else 0.0) for other in boxes
        ) if boxes and area else 0.0
        if covered < BBOX_COVERAGE:
            problems.append(
                f"{project}: opening {label} bbox {box} does not sit on any text "
                f"found on page {page_number} (covers {covered:.0%}). It was not "
                "measured - take it from the extractor's row, do not construct one"
            )
    return problems, warnings
def _valid_page_size(page_size: Any) -> bool:
    if not isinstance(page_size, dict):
        return False
    width, height = page_size.get("width"), page_size.get("height")
    return isinstance(width, (int, float)) and isinstance(height, (int, float)) and width > 0 and height > 0


def _normalize_opening(opening: dict[str, Any]) -> dict[str, Any]:
    """Apply field aliases in place for validation."""
    if opening.get("hardware_set") is None and opening.get("hw_set") is not None:
        opening["hardware_set"] = opening["hw_set"]
    if opening.get("door_number") is None and opening.get("mark"):
        opening["door_number"] = opening["mark"]
    # Parser sometimes leaves bbox null while row_bbox / cell_boxes are intact.
    if not _valid_bbox(opening.get("bbox")):
        if _valid_bbox(opening.get("row_bbox")):
            opening["bbox"] = list(opening["row_bbox"])
        else:
            cells = opening.get("cell_boxes")
            if isinstance(cells, list) and cells:
                valid_cells = [c for c in cells if _valid_bbox(c)]
                if valid_cells:
                    x0 = min(float(c[0]) for c in valid_cells)
                    y0 = min(float(c[1]) for c in valid_cells)
                    x1 = max(float(c[2]) for c in valid_cells)
                    y1 = max(float(c[3]) for c in valid_cells)
                    opening["bbox"] = [x0, y0, x1, y1]
    return opening
def _no_scope_declared(payload: Any) -> str:
    """However a take-off says "this set has no Division 08 scope".

    Read the finding, do not demand a spelling of it. A real run wrote
    `door_schedule_found: false` with `door_schedule_pages: []` and a list of
    existing-to-remain doors - unambiguous, and rejected for the wrong word.
    """
    if not isinstance(payload, dict):
        return ""
    reason = str(payload.get("no_scope_reason") or "").strip()
    if reason:
        return reason
    for field in ("door_schedule_found", "schedule_found", "has_division_08_scope"):
        if payload.get(field) is False:
            return f"{field}: false"
    return ""


def _sheetmap_says_a_schedule_exists(project: str) -> list[int]:
    """Pages the deterministic pre-pass found a schedule marker on.

    This is the evidence that separates "the set has no doors" from "the take-off
    missed the schedule". Absent or unreadable, it claims nothing: an older
    sheet map without these keys must not turn a correct run into a failure.
    """
    path = storage_root() / project / "extracted" / "_sheetmap.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    pages: list[int] = []
    for entry in (payload.get("files") or []) if isinstance(payload, dict) else []:
        if not isinstance(entry, dict):
            continue
        recorded = entry.get("schedule_pages")
        if isinstance(recorded, list):
            pages.extend(int(p) for p in recorded if isinstance(p, (int, float)))
            continue
        # Older map: derive it from the per-page kind rather than claiming none.
        for page in entry.get("pages") or []:
            if isinstance(page, dict) and page.get("kind") == "schedule":
                pages.append(int(page["source_page"]))
    return sorted(set(pages))


def _sheetmap_door_schedule_candidates(project: str) -> list[int]:
    """Pages that may hold a door schedule even without a text-layer marker.

    Includes explicit ``door_schedule_candidate_pages`` and any page whose roles
    include ``door_schedule`` / ``door_schedule_candidate`` (e.g. A4.0 CAD sheets
    with title-block-only text). Empty openings over these pages is a missed read.
    """
    path = storage_root() / project / "extracted" / "_sheetmap.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    pages: list[int] = []
    for entry in (payload.get("files") or []) if isinstance(payload, dict) else []:
        if not isinstance(entry, dict):
            continue
        recorded = entry.get("door_schedule_candidate_pages")
        if isinstance(recorded, list):
            pages.extend(int(p) for p in recorded if isinstance(p, (int, float)))
        for page in entry.get("pages") or []:
            if not isinstance(page, dict):
                continue
            roles = {str(r).lower() for r in (page.get("roles") or [])}
            if roles & {"door_schedule", "door_schedule_candidate"}:
                try:
                    pages.append(int(page["source_page"]))
                except (KeyError, TypeError, ValueError):
                    continue
    return sorted(set(pages))


def _sheetmap_needs_visual_read_pages(project: str) -> list[tuple[str, int]]:
    """(path, page) pairs sheetmap marked for forced vision."""
    path = storage_root() / project / "extracted" / "_sheetmap.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    hits: list[tuple[str, int]] = []
    for entry in (payload.get("files") or []) if isinstance(payload, dict) else []:
        if not isinstance(entry, dict):
            continue
        file_path = str(entry.get("path") or "")
        recorded = entry.get("needs_visual_read_pages")
        if isinstance(recorded, list):
            for page in recorded:
                try:
                    hits.append((file_path, int(page)))
                except (TypeError, ValueError):
                    continue
        for page in entry.get("pages") or []:
            if not isinstance(page, dict) or not page.get("needs_visual_read"):
                continue
            try:
                hits.append((file_path, int(page["source_page"])))
            except (KeyError, TypeError, ValueError):
                continue
    return sorted(set(hits))


def _visual_manifest_schedule_pages(project: str) -> list[tuple[str, int]]:
    """Mandatory vision pages that are schedule/candidate related.

    `_visual_pages.json` also lists FRP / finish / bare-hardware / generic
    MinerU-null sheets. Those must be vision-read by their own specialists —
    they are not a door_schedule checklist item. Only pages whose roles (or
    schedule-specific reasons) mark them as door schedule work gate this
    artifact. Shared filter: ``visual_pages.is_door_schedule_visual_page``.
    """
    from cbc.modules.extraction.infrastructure.visual_pages import (
        is_door_schedule_visual_page,
    )

    path = storage_root() / project / "extracted" / "_visual_pages.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    hits: list[tuple[str, int]] = []
    for page in (payload.get("pages") or []) if isinstance(payload, dict) else []:
        if not isinstance(page, dict) or not is_door_schedule_visual_page(page):
            continue
        try:
            hits.append((str(page.get("path") or ""), int(page["source_page"])))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(set(hits))


def _visual_pages_checked_keys(payload: Any) -> set[tuple[str, int]]:
    if not isinstance(payload, dict):
        return set()
    checked = payload.get("visual_pages_checked")
    if not isinstance(checked, list):
        return set()
    keys: set[tuple[str, int]] = set()
    for row in checked:
        if not isinstance(row, dict):
            continue
        try:
            keys.add((str(row.get("path") or ""), int(row["source_page"])))
        except (KeyError, TypeError, ValueError):
            continue
    return keys


def _normalize_visual_key(path: str, page: int) -> tuple[str, int]:
    """Compare by basename + page so projects/... vs bare names still match."""
    name = Path(str(path).replace("\\", "/")).name
    return (name, int(page))


def _extraction_found_no_scope(project: str) -> bool:
    """True when the take-off recorded an empty set that nothing contradicts.

    Read from the artifact rather than passed down, because the pricing and
    proposal gates run as independent checks and must reach the same verdict the
    extraction gate did.
    """
    path = storage_root() / project / "extracted" / "door_schedule.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if isinstance(payload, list):
        openings: Any = payload
    elif isinstance(payload, dict):
        openings = payload.get("openings")
        if not openings and isinstance(payload.get("lines"), list):
            openings = payload["lines"]
        openings = openings or []
    else:
        return False
    if openings:
        return False
    # A schedule the pre-pass found (marker or sheet-ID candidate) and the
    # take-off did not read is a missed read, and must not silence pricing.
    if _sheetmap_says_a_schedule_exists(project):
        return False
    if _sheetmap_door_schedule_candidates(project):
        return False
    return True


def check_extraction(project: str, *, require_scope: bool = False) -> tuple[list[str], list[str]]:
    """Return (problems, warnings) for extraction artifacts."""
    problems: list[str] = []
    warnings: list[str] = []
    extracted = storage_root() / project / "extracted"

    if not extracted.exists():
        problems.append(f"{project}: no extracted/ directory")
        return problems, warnings

    if require_scope:
        for name in ("scope_metadata.json", "scope_summary.json"):
            if not (extracted / name).exists():
                problems.append(f"{project}: missing extracted/{name}")

    schedule_path = extracted / "door_schedule.json"
    if not schedule_path.exists():
        problems.append(f"{project}: door_schedule.json not written")
        return problems, warnings

    try:
        payload = json.loads(schedule_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        problems.append(f"{project}: door_schedule.json is not valid JSON: {exc}")
        return problems, warnings

    # Take the same shapes the importer takes, and no fewer. This gate runs
    # first, so anything it refuses never reaches sync - and it was refusing a
    # bare array that `_normalize_schedule_payload` has always accepted, and a
    # `lines` wrapper that a run produced with every opening intact. A gate
    # stricter than the thing it guards fails work that would have imported
    # cleanly. What each opening must contain is checked below, unchanged.
    if isinstance(payload, list):
        openings = payload
    elif isinstance(payload, dict):
        openings = payload.get("openings")
        if not openings and isinstance(payload.get("lines"), list):
            openings = payload["lines"]
        openings = openings or []
    else:
        problems.append(f"{project}: door_schedule.json must be a JSON object or an array")
        return problems, warnings
    # A bid set with no Division 08 openings is a finding, not a failed read.
    #
    # A Dunkin' remodel came through as tile, paint and vinyl wall covering, and
    # the estimator was shown "Automatic read didn't finish". Requiring the file
    # to exist fixed half of it; then the take-off wrote a thorough one saying
    # `door_schedule_found: false` and the gate rejected it for not using the
    # word `no_scope_reason`. A gate that demands a particular spelling of a
    # finding it can already read is stricter than the thing it guards.
    #
    # So the evidence decides, not the vocabulary. The one case that genuinely
    # is a failed read - the sheet map found a schedule and the take-off returned
    # nothing - is the one that still fails.
    if not openings:
        declared = _no_scope_declared(payload)
        missed = _sheetmap_says_a_schedule_exists(project)
        candidates = _sheetmap_door_schedule_candidates(project)
        if missed:
            problems.append(
                f"{project}: door_schedule.json has no openings, but the sheet map "
                f"found a schedule on page(s) {missed}. Re-read those pages (use "
                f"`_visual_pages.json` / get_page_image); an empty take-off over a "
                "set that has a schedule is a missed read, not a no-scope bid."
            )
        elif candidates:
            problems.append(
                f"{project}: door_schedule.json has no openings, but the sheet map "
                f"flagged door-schedule candidate page(s) {candidates} "
                "(sheet-ID / text-poor CAD heuristic). Open those pages with "
                "get_page_image / `_visual_pages.json` and record "
                "`visual_pages_checked` before declaring no_scope; empty openings "
                "over a candidate schedule sheet is a missed read."
            )
        else:
            warnings.append(
                f"{project}: no Division 08 openings - "
                f"{declared or 'no reason recorded'}"
            )

    # Forced visual-read checklist: schedule/candidate pages in the pre-render
    # manifest must appear in visual_pages_checked (path basename + page).
    visual_required = _visual_manifest_schedule_pages(project)
    sheetmap_visual = _sheetmap_needs_visual_read_pages(project)
    visual_path = storage_root() / project / "extracted" / "_visual_pages.json"
    if sheetmap_visual and not visual_path.is_file():
        problems.append(
            f"{project}: sheetmap lists needs_visual_read_pages {sheetmap_visual} "
            "but extracted/_visual_pages.json is missing — worker prepare must "
            "pre-render those pages before Claude runs."
        )
    if visual_required:
        checked = {
            _normalize_visual_key(path, page)
            for path, page in _visual_pages_checked_keys(payload)
        }
        missing = [
            (path, page)
            for path, page in visual_required
            if _normalize_visual_key(path, page) not in checked
        ]
        if missing:
            problems.append(
                f"{project}: door_schedule.json is missing visual_pages_checked "
                f"coverage for mandatory vision page(s) {missing}. Read each "
                "`_visual_pages.json` image and record "
                "{path, source_page, image_path, finding} before save / no_scope."
            )

    for opening in openings:
        opening = _normalize_opening(opening)
        label = opening.get("door_number") or opening.get("description") or "?"
        if opening.get("hw_set") and not opening.get("hardware_set"):
            warnings.append(f"{project}: opening {label} uses hw_set; prefer hardware_set")

        # A line the estimator added by hand was never read off a drawing, so it has
        # no page, no bbox and no door number - a hand dryer nobody drew is still a
        # line on the quote. Every one of those checks fired on it, reporting five
        # problems against a healthy project, and the same demand one layer down
        # made a pricing pass invent a page number to satisfy it (NFR-2).
        #
        # What still applies is the part that is about the estimator's own entry:
        # it needs something to identify it, and a confidence score.
        if _added_by_hand(opening):
            if not (opening.get("description") or opening.get("door_number")):
                problems.append(
                    f"{project}: hand-added opening has neither a door_number nor a "
                    "description - nothing identifies it on the quote"
                )
            if opening.get("confidence") is None:
                problems.append(
                    f"{project}: hand-added opening {label} has no confidence score (NFR-2)"
                )
            continue

        for field in HARD_FIELDS:
            if not opening.get(field):
                problems.append(f"{project}: opening {label} is missing {field}")
        if not (opening.get("size") or (opening.get("width") and opening.get("height"))):
            problems.append(f"{project}: opening {label} has no resolvable size")
        if opening.get("confidence") is None:
            problems.append(f"{project}: opening {label} has no confidence score (NFR-2)")
        if not _valid_bbox(opening.get("bbox")):
            problems.append(f"{project}: opening {label} has no valid bbox (NFR-3)")
        if not _valid_page_size(opening.get("page_size")):
            problems.append(f"{project}: opening {label} has no valid page_size (NFR-3)")
        for field in SOFT_FIELDS:
            if opening.get(field) is None:
                warnings.append(f"{project}: opening {label} is missing {field}")
        # pdf-verify-before-present: missing/low-confidence claims need a page citation.
        flags = opening.get("flags") or []
        if isinstance(flags, list):
            missingish = [
                f for f in flags if isinstance(f, str) and f.endswith("_missing")
            ]
        else:
            missingish = []
        confidence = opening.get("confidence")
        low_conf = (
            isinstance(confidence, (int, float))
            and not isinstance(confidence, bool)
            and confidence < CONFIDENCE_FLOOR
        )
        if missingish or low_conf or any(
            opening.get(field) is None for field in ("fire_rating", "handing")
        ):
            evidence = str(opening.get("evidence_note") or "")
            if not (
                re.search(r"page\s*\d+", evidence, re.I)
                or re.search(r"source_page", evidence, re.I)
                or re.search(r"pdf-tools|bid-docs|extract_text|get_page", evidence, re.I)
            ):
                warnings.append(
                    f"{project}: opening {label} has unresolved fields or low "
                    "confidence without a PDF page citation in evidence_note "
                    "(pdf-verify-before-present)"
                )

    # Shape is checked above; this checks the numbers are real. It opens the
    # sheet, so it runs once per page rather than once per opening.
    box_problems, box_warnings = check_bboxes_are_real(project, openings)
    problems.extend(box_problems)
    warnings.extend(box_warnings)

    frp_path = extracted / "frp_takeoff.json"
    scope_path = extracted / "scope_summary.json"
    frp_in_scope = False
    if scope_path.exists():
        try:
            scope = json.loads(scope_path.read_text(encoding="utf-8"))
            if isinstance(scope, dict):
                frp_in_scope = bool(scope.get("frp_in_scope"))
        except (OSError, json.JSONDecodeError):
            pass
    if frp_in_scope and not frp_path.exists():
        problems.append(
            f"{project}: frp_in_scope is true but extracted/frp_takeoff.json "
            "was not written — run frp-specialist or clear the flag"
        )
    if frp_path.exists():
        try:
            frp = json.loads(frp_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"{project}: frp_takeoff.json is not valid JSON: {exc}")
            return problems, warnings
        if not frp_in_scope:
            warnings.append(
                f"{project}: frp_takeoff.json present while frp_in_scope is false "
                "(unnecessary FRP pass — prefer skipping when the flag is false)"
            )
        if frp.get("status") == "PENDING_CONSTANTS":
            warnings.append(f"{project}: FRP quantities blocked - conversion constants pending (Open Item 5)")
        # The seeded floor. It satisfies "the file exists" so the run is not
        # stopped, and it must never pass for a finished measurement.
        if frp.get("status") == "NOT_MEASURED":
            warnings.append(
                f"{project}: FRP is in scope and has not been measured - "
                "perimeter, corners and wall height still owed"
            )

    div10_path = extracted / "div10_takeoff.json"
    div10_in_scope = False
    if scope_path.exists():
        try:
            scope = json.loads(scope_path.read_text(encoding="utf-8"))
            if isinstance(scope, dict):
                div10_in_scope = bool(scope.get("div10_in_scope"))
        except (OSError, json.JSONDecodeError):
            pass
    if div10_in_scope and not div10_path.exists():
        problems.append(
            f"{project}: div10_in_scope is true but extracted/div10_takeoff.json "
            "was not written — run div10-specialist or clear the flag"
        )
    if div10_path.exists():
        try:
            div10 = json.loads(div10_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"{project}: div10_takeoff.json is not valid JSON: {exc}")
            return problems, warnings
        if not div10_in_scope:
            warnings.append(
                f"{project}: div10_takeoff.json present while div10_in_scope is false "
                "(unnecessary Div 10 pass — prefer skipping when the flag is false)"
            )
        items = div10.get("items") if isinstance(div10, dict) else None
        if div10_in_scope and isinstance(items, list) and not items and not div10.get("no_scope_reason"):
            warnings.append(
                f"{project}: Div 10 is in scope but div10_takeoff.json has no items"
            )

    return problems, warnings
def check_pricing(project: str, *, require_hardware_sets: bool = False) -> tuple[list[str], list[str]]:
    """Return (problems, warnings) for priced artifacts."""
    problems: list[str] = []
    warnings: list[str] = []
    root = storage_root() / project

    # Nothing in scope means nothing to price, and that is not a pricing failure.
    # Fixing this only at extraction left the same bug one layer down: a
    # finishes-only bid passed its take-off and then failed the pipeline at
    # pricing for the empty quote that take-off had correctly predicted.
    if _extraction_found_no_scope(project):
        warnings.append(
            f"{project}: nothing priced - the take-off found no Division 08 "
            "openings in this bid set"
        )
        return problems, warnings

    if require_hardware_sets:
        hw_path = root / "extracted" / "hardware_sets.json"
        if not hw_path.exists():
            problems.append(f"{project}: missing extracted/hardware_sets.json")

    priced_path = root / "priced" / "line_items.json"
    if not priced_path.exists():
        problems.append(f"{project}: priced/line_items.json not written")
        return problems, warnings

    try:
        payload = json.loads(priced_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        problems.append(f"{project}: priced/line_items.json is not valid JSON: {exc}")
        return problems, warnings

    # Either shape. A run writes a bare array about as often as the wrapped
    # object it is asked for, and rejecting the array here returned before a
    # single pricing rule ran - so the shape decided whether the checks happened.
    # Agents also emit `line_items` (same name as the file) instead of `lines`.
    from cbc.modules.extraction.api.normalize_artifacts import (
        normalize_priced_quote_payload,
    )

    payload = normalize_priced_quote_payload(payload)
    lines = payload if isinstance(payload, list) else (
        payload.get("lines") if isinstance(payload, dict) else None
    )
    if not isinstance(lines, list) or not lines:
        problems.append(f"{project}: priced/line_items.json must contain a non-empty lines array")
        return problems, warnings

    priced_count = 0
    for index, line in enumerate(lines, start=1):
        label = line.get("line_id") or (line.get("description") or f"line {index}")[:40]
        for field in PRICING_LINE_FIELDS:
            if line.get(field) is None or line.get(field) == "":
                problems.append(f"{project}: priced line {label} is missing {field}")

        # A line has to say what it is. The matcher records the specified item -
        # "IVES 700 83\", 630" - and a run that dropped it wrote 25 blank MANUAL
        # rows: not wrong, but useless to the estimator who has to price them.
        if not (line.get("part_number") or line.get("description")):
            problems.append(
                f"{project}: priced line {label} has neither part_number nor description "
                "- carry the specified item across from hardware_sets.json"
            )
        # NFR-3: an unauditable line is not a line - but "auditable" is not the same
        # question for every line.
        #
        # A door or an FRP run comes off a drawing, so it has a page and must name
        # it. An accessory often does not: the estimator adds a hand dryer nobody
        # drew, and there is no page to point at. Demanding one anyway rejected a
        # correctly priced hand-added accessory and took the whole quote with it -
        # and on the retry the pass satisfied the rule by *inventing* a page,
        # putting the hand dryer on the door-schedule sheet. A check that makes
        # fabrication the cheapest way out is worse than the gap it was closing
        # (NFR-2).
        #
        # So the accessory must still be traceable, by the half of NFR-3 that
        # applies to it: where its price came from.
        from_a_drawing = line.get("group_type") in ("door", "frp")
        if line.get("source_page") is None:
            if from_a_drawing:
                problems.append(f"{project}: priced line {label} has no source_page")
            elif not str(line.get("cost_source_detail") or "").strip():
                problems.append(
                    f"{project}: line {label} has neither a source_page nor a "
                    "cost_source_detail - a line off the drawings must name its page, "
                    "and one added by hand must name where its price came from (NFR-3)"
                )
        # NFR-2: a manual line is an instruction to a human, so it says why.
        if line.get("cost_source") == "MANUAL" and not str(
            line.get("cost_source_detail") or line.get("reason") or ""
        ).strip():
            problems.append(
                f"{project}: MANUAL line {label} records no reason - say why it "
                "cannot be priced automatically"
            )

        # A line has to say what it is. An autopilot run wrote ten lines whose
        # part_number was null and whose whole identity was "Manual entry
        # required - wood door" - technically honest, and useless: an estimator
        # cannot price an item the quote does not name. Carrying the specified
        # part across from hardware_sets.json is the pass's job even, and
        # especially, when nothing matched (NFR-2).
        if not (line.get("part_number") or "").strip() and not (
            line.get("description") or ""
        ).strip():
            problems.append(
                f"{project}: line {label} names neither a part_number nor a "
                "description - nothing on it tells an estimator what to price. "
                "Copy the specified item across even when no match was found"
            )

        # A cost a run writes must come from somewhere a run can actually read.
        #
        # Allowed: P21 last-PO, list×multiplier from a page, special-net sheet,
        # or catalog.md baseline (Path 2b). DISTRIBUTOR_MANUAL, VENDOR_RFQ and
        # MANUAL mean a person supplied the number - there is no distributor on
        # the phone during a pipeline run - so from a run they carry no cost.
        #
        # This started as a narrower rule that named MANUAL alone. The next run
        # relabelled 34 invented costs as DISTRIBUTOR_MANUAL and passed. Naming
        # one label taught the pass which label to avoid, so the rule now names
        # what a run may legitimately obtain instead (NFR-2).
        if (
            line.get("cost") is not None
            and line.get("cost_source") not in _COST_SOURCES_A_RUN_CAN_READ
            and not _added_by_hand(line)
        ):
            problems.append(
                f"{project}: line {label} is {line.get('cost_source')} and carries a "
                f"cost of {line['cost']}. That source means a person supplied the "
                "number, and no person did. Leave cost null and say what the "
                "estimator needs to look up"
            )

        # And it may not claim someone signed off on it.
        #
        # Every one of those 34 lines read "Estimator approved cost: ...". No
        # estimator had seen the quote. An invented number is a gap; an invented
        # number wearing a human's approval is a gap nobody will look for (NFR-1).
        detail_text = str(line.get("cost_source_detail") or "")
        if not _added_by_hand(line) and _CLAIMS_APPROVAL.search(detail_text):
            problems.append(
                f"{project}: line {label} says {detail_text[:52]!r}. A run cannot "
                "record an approval on the estimator's behalf - that is the one "
                "thing it is not allowed to do"
            )

        # A computed cost has to name the sheet (or baseline) it was read from.
        #
        # The same run put three different costs on one part number and cited
        # `source_page: 14` for all of them - the bid set's door-schedule page,
        # not a price book. `cost_source_detail` said "Price based on Pemko
        # catalog", which names no page anyone can open. The catalog tools hand
        # back a file name and a locator precisely so this citation is available
        # (NFR-3). Path 2b may cite catalog.md instead of a PDF page.
        if line.get("cost_source") == "LIST_X_MULTIPLIER":
            detail = str(line.get("cost_source_detail") or "")
            if not (_CATALOG_FILE.search(detail) or _BASELINE_CITATION.search(detail)):
                problems.append(
                    f"{project}: line {label} claims list x multiplier but its "
                    f"cost_source_detail ({detail[:48]!r}) names no price-book file "
                    "or catalog.md. Quote the file_path and locator find_pages "
                    "returned, or the catalog.md baseline citation"
                )
        if line.get("cost_source") == "SPECIAL_NET":
            detail = str(line.get("cost_source_detail") or "")
            if not _SPECIAL_NET_CITATION.search(detail):
                problems.append(
                    f"{project}: line {label} claims SPECIAL_NET but its "
                    f"cost_source_detail ({detail[:48]!r}) does not cite a special "
                    "net / item code. Record get_special_net (or sheet) provenance"
                )
        if line.get("cost_source") == "CATALOG_BASELINE":
            detail = str(line.get("cost_source_detail") or "")
            if not _BASELINE_CITATION.search(detail):
                problems.append(
                    f"{project}: line {label} claims CATALOG_BASELINE but its "
                    f"cost_source_detail ({detail[:48]!r}) does not cite catalog.md. "
                    "Record the lookup_catalog_item citation"
                )
        # A computed source must carry a number. Runs that found a multiplier and
        # page citation but stopped at MANUAL with cost null leave a quote that
        # looks partially priced and validates as complete.
        if line.get("cost") is None and line.get("cost_source") in (
            "LIST_X_MULTIPLIER",
            "SPECIAL_NET",
            "CATALOG_BASELINE",
            "P21_LAST_PO",
        ):
            problems.append(
                f"{project}: line {label} is {line.get('cost_source')} but cost "
                "is null — finish the lookup via calc-engine or use MANUAL with "
                "no multiplier metadata"
            )
        if (
            line.get("cost") is None
            and line.get("cost_source") == "MANUAL"
            and line.get("multiplier") is not None
            and str(line.get("price_book_version") or "").strip()
        ):
            problems.append(
                f"{project}: line {label} records multiplier and price-book "
                "metadata under MANUAL with no cost — complete Path 2 list×"
                "multiplier or remove the multiplier fields"
            )
        if line.get("cost") is not None:
            priced_count += 1
        group_type = line.get("group_type")
        if group_type and group_type not in PRICING_GROUP_TYPES:
            warnings.append(f"{project}: priced line {label} has unusual group_type {group_type!r}")
        cost = line.get("cost")
        if cost is not None:
            try:
                parsed = float(cost)
            except (TypeError, ValueError):
                problems.append(f"{project}: priced line {label} has unreadable cost")
            else:
                if parsed < 0:
                    problems.append(f"{project}: priced line {label} has negative cost")
                elif line.get("sale_ea") is None or line.get("ext_price") is None:
                    problems.append(
                        f"{project}: priced line {label} has cost but missing sale_ea or ext_price"
                    )

    # Not errors: an all-Allegion bid legitimately prices nothing automatically
    # (CLAUDE.md - bought via Banner or SecLock, so manual entry). The point is
    # that the quote says so rather than looking finished.
    if priced_count == 0:
        warnings.append(
            f"{project}: not one of {len(lines)} line(s) carries a price - this quote "
            "is entirely manual and is not ready to send to anyone"
        )

    hw_path = root / "extracted" / "hardware_sets.json"
    if hw_path.exists():
        try:
            groups = json.loads(hw_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            groups = []
        specified = {
            str(entry.get("hardware_set"))
            for entry in (groups if isinstance(groups, list) else [])
            if entry.get("hardware_set")
        }
        quoted = {str(line.get("group")) for line in lines if line.get("group")}
        for missing in sorted(specified - quoted):
            warnings.append(
                f"{project}: hardware {missing} was extracted but has no line on the quote"
            )

    problems.extend(_priced_off_a_page_the_catalog_already_answers(project, lines))

    return problems, warnings


def _priced_off_a_page_the_catalog_already_answers(
    project: str, lines: list[dict[str, Any]]
) -> list[str]:
    """Lines read off a PDF for a part the product catalog holds.

    A run priced `PEMKO-275A-42` at $12.41 from price-book page 520, cross-read
    against a different part (NGP 431S), while `catalogItems` held Pemko 275A at
    $7.16 - 73% high, citing the wrong code. Nothing caught it, because every
    other rule here was satisfied: it had a page, a multiplier and a citation.

    The rule is not "never open a PDF". It is that the catalog is Path 2b and the
    sheet is Path 2, so reaching the sheet for a part the catalog answers means
    the pass skipped a step - and the number it brought back disagreed.
    """
    from cbc.modules.catalog.api.pageindex import reader

    suspects = [
        line
        for line in lines
        if line.get("cost_source") == "LIST_X_MULTIPLIER"
        and (line.get("part_number") or "").strip()
        and _CATALOG_FILE.search(str(line.get("cost_source_detail") or ""))
    ]
    if not suspects:
        return []

    problems: list[str] = []
    for line in suspects:
        part = str(line.get("part_number")).strip()
        try:
            row = reader.lookup_catalog_item(part)
        except Exception:
            # No read-only credential here, or no catalog: that is a reason to
            # skip the cross-check, never to fail a quote over it.
            return []
        if row is None:
            continue
        label = line.get("line_id") or (line.get("description") or part)[:40]
        problems.append(
            f"{project}: line {label} was priced off a price-book page, but the "
            f"product catalog holds {row.get('manufacturer')} {row.get('part')} at "
            f"cost {row.get('cost')} (matched on {row.get('matchedOn')!r}). Call "
            "lookup_catalog_item first and cite the catalog, or say in "
            "cost_source_detail why the sheet price is the right one"
        )
    return problems


def check_delivery_readiness(project: str) -> tuple[list[str], list[str]]:
    """Gate customer-facing output, while leaving extraction/pricing review usable.

    A manual cut-off is valid pricing output, but is not a priced quotation.
    Recompute from source data rather than trusting flags or summary counters.
    """
    from cbc.modules.extraction.api.normalize_artifacts import (
        normalize_door_schedule_payload,
        normalize_priced_quote_payload,
    )
    from cbc.modules.pricing.api.confidence import CONFIDENCE_FLOOR

    root = storage_root() / project
    problems: list[str] = []
    warnings: list[str] = []

    def read(relative: str, *, required: bool = True) -> Any:
        path = root / relative
        if not path.is_file() and not required:
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"{project}: cannot verify delivery input {relative}: {exc}")
            return {}

    metadata = read("extracted/scope_metadata.json")
    if isinstance(metadata, dict) and metadata.get("brand_mismatch_warning"):
        warnings.append(
            f"{project}: unresolved brand/project identity mismatch — confirm the "
            "correct bid and source documents before sending "
            f"({metadata.get('brand_mismatch_warning')})"
        )

    if _extraction_found_no_scope(project):
        return problems, warnings

    schedule = normalize_door_schedule_payload(read("extracted/door_schedule.json"))
    openings = schedule.get("openings", []) if isinstance(schedule, dict) else schedule
    if not isinstance(openings, list):
        problems.append(f"{project}: cannot verify delivery openings")
        openings = []
    for index, opening in enumerate(openings, start=1):
        if not isinstance(opening, dict):
            problems.append(f"{project}: opening {index} is not an object")
            continue
        if _added_by_hand(opening) and not opening.get("door_number"):
            continue  # A hand-added accessory has no door handing or fire rating.
        label = opening.get("door_number") or opening.get("mark") or index
        for field in ("fire_rating", "handing"):
            value = opening.get(field)
            if value is None or str(value).strip().lower() in (
                "", "unknown", "tbd", "not specified", "unspecified",
            ):
                problems.append(
                    f"{project}: opening {label} has unresolved {field} — correct "
                    "it from the source or record the estimator's actual value before delivery"
                )
        confidence = opening.get("confidence")
        if (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not math.isfinite(confidence)
            or confidence < CONFIDENCE_FLOOR
        ) and not opening.get("confirmed_by"):
            problems.append(
                f"{project}: opening {label} confidence is below {CONFIDENCE_FLOOR} "
                "or missing — an estimator must review and confirm the match before delivery"
            )

    priced = normalize_priced_quote_payload(read("priced/line_items.json"))
    lines = priced.get("lines", []) if isinstance(priced, dict) else priced
    if not isinstance(lines, list) or not lines:
        problems.append(f"{project}: no quote lines — customer-facing delivery is blocked")
        return problems, warnings
    priced_count = 0
    for index, line in enumerate(lines, start=1):
        if not isinstance(line, dict):
            problems.append(f"{project}: quote line {index} is not an object")
            continue
        cost = line.get("cost")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool) and math.isfinite(cost) and cost >= 0:
            priced_count += 1
        confidence = line.get("confidence")
        if confidence is not None and (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not math.isfinite(confidence)
            or confidence < CONFIDENCE_FLOOR
        ):
            problems.append(
                f"{project}: quote line {line.get('line_id') or index} match confidence "
                f"is below {CONFIDENCE_FLOOR} — resolve the match before delivery"
            )
    if not priced_count:
        problems.append(
            f"{project}: no quote line has a verified cost — manual pricing is still "
            "required; customer-facing delivery is blocked"
        )
    elif priced_count < len(lines):
        warnings.append(f"{project}: {len(lines) - priced_count} quote line(s) still need an estimator price")
    return problems, warnings


def check_proposal(project: str) -> tuple[list[str], list[str]]:
    """Return (problems, warnings) for proposal artifacts."""
    # Same reasoning as check_pricing: there is no quotation to render for a bid
    # CBC is not quoting. The estimator gets the no_scope review flag instead.
    #
    # This has to run *before* the delivery-readiness pass, not after it. It used
    # to short-circuit on the line below, by which point that pass had already
    # added its own problems - so a finishes-only bid failed the proposal gate
    # over delivery inputs that a bid with nothing to deliver was never going to
    # have, which is the exact failure this branch exists to prevent.
    if _extraction_found_no_scope(project):
        return [], [f"{project}: no proposal - the take-off found no Division 08 openings"]

    problems, warnings = check_delivery_readiness(project)
    root = storage_root() / project

    if not (root / "quotation.html").exists():
        problems.append(f"{project}: quotation.html not written")
    if not (root / "review" / "review_flags.json").exists():
        problems.append(f"{project}: review/review_flags.json not written")
    if not (root / "review" / "review_summary.html").exists():
        warnings.append(f"{project}: review/review_summary.html not written")
    if not (root / "review" / "quotation_email_draft.md").exists():
        warnings.append(f"{project}: review/quotation_email_draft.md not written")

    # The same structural check quoting runs when it renders. Reaching into
    # quoting for it closed the last cycle in the module graph; the check itself
    # knows about neither module, so it lives in `shared`.
    problems.extend(
        pdfcheck.exported_pdf_problems(
            root, project, ("quotation.pdf", "uploads/final/quotation.pdf")
        )
    )

    return problems, warnings


# Which checks each job type has to pass before its output reaches MongoDB.
#
# A dict rather than an if/elif chain because the chain ended in `else: return`,
# and a job type nobody remembered to add fell through it silently. That is
# exactly what happened to `run_full_pipeline`: the one path with no human
# checkpoints was also the one path with no artifact checks. GATED_JOB_TYPES
# below asserts the mapping stays complete.
ARTIFACT_CHECKS: dict[str, tuple] = {
    "extract_bid_set": (lambda slug: check_extraction(slug, require_scope=True),),
    "rerun_extraction": (lambda slug: check_extraction(slug, require_scope=False),),
    "match_and_price": (lambda slug: check_pricing(slug, require_hardware_sets=True),),
    "build_proposal": (check_proposal,),
    # One session produced all three, so all three are checked.
    "run_full_pipeline": (
        lambda slug: check_extraction(slug, require_scope=True),
        lambda slug: check_pricing(slug, require_hardware_sets=True),
        check_proposal,
    ),
}
PHASE_LABELS: dict[str, tuple[str, ...]] = {
    "extract_bid_set": ("extraction",),
    "rerun_extraction": ("extraction",),
    "match_and_price": ("pricing",),
    "build_proposal": ("proposal",),
    "run_full_pipeline": ("extraction", "pricing", "proposal"),
}
PHASE_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "extraction": (
        "extracted/door_schedule.json",
        "extracted/scope_metadata.json",
        "extracted/scope_summary.json",
        "extracted/frp_takeoff.json",
        "extracted/div10_takeoff.json",
        "extracted/hardware_sets.json",
    ),
    "pricing": (
        "priced/line_items.json",
        "priced/margin_applied.json",
        "extracted/hardware_sets.json",
    ),
    "proposal": (
        "quotation.html",
        "quotation.pdf",
        "review/review_flags.json",
        "review/quotation_email_draft.md",
    ),
}
UNCHECKED_JOB_TYPES = frozenset(
    {
        "ingest_pricebook",
        "ingest_addendum",
        "index_catalog",
        "delete_catalog",
        "parse_document",
        "parse_catalog",
        "parse_multiplier",
    }
)


def _file_sha(project: str, relative: str) -> str | None:
    path = storage_root() / project / relative
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _phase_record(project: str, phase: str) -> dict[str, Any]:
    artifacts = {}
    for relative in PHASE_ARTIFACTS.get(phase, ()):
        sha = _file_sha(project, relative)
        if sha:
            artifacts[relative] = sha
    record: dict[str, Any] = {
        "passed": True,
        "validatedAt": datetime.now(timezone.utc).isoformat(),
        "artifacts": artifacts,
    }
    if phase == "pricing":
        from cbc.worker_kit.sandbox import _priced_line_count

        record["lineCount"] = _priced_line_count(
            storage_root() / project / "priced" / "line_items.json"
        ) or 0
        path = storage_root() / project / "priced" / "line_items.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, json.JSONDecodeError):
            payload = {}
        rows = []
        if isinstance(payload, dict):
            rows = payload.get("lines") or payload.get("line_items") or []
        elif isinstance(payload, list):
            rows = payload
        if isinstance(rows, list):
            record["pricedCount"] = sum(
                1
                for row in rows
                if isinstance(row, dict)
                and isinstance(row.get("cost"), (int, float))
                and not isinstance(row.get("cost"), bool)
            )
    return record


def validate_job_artifacts(job_type: str, project_slug: str) -> dict[str, Any] | None:
    """Raise ArtifactValidationError if job artifacts fail validation (worker gate).

    `run_full_pipeline` is fail-fast: extraction, then pricing, then proposal.
    The first failing phase is named in the error; later checks do not run.
    Passing phases are returned (and attached to the error) as `phaseState`.
    """
    problems: list[str] = []
    warnings: list[str] = []
    phase_state: dict[str, Any] = {}

    checks = ARTIFACT_CHECKS.get(job_type)
    if checks is None:
        if job_type not in UNCHECKED_JOB_TYPES:
            # Better a loud failure than a job quietly skipping its own gate.
            raise ArtifactValidationError(
                f"job type {job_type!r} has no entry in ARTIFACT_CHECKS and is not "
                "listed as unchecked - add it to one or the other"
            )
        return None

    labels = PHASE_LABELS.get(job_type, ())
    fail_fast = job_type == "run_full_pipeline"

    for index, check in enumerate(checks):
        phase = labels[index] if index < len(labels) else f"check_{index}"
        p, w = check(project_slug)
        warnings.extend(w)
        if p:
            detail = "; ".join(p[:5])
            if len(p) > 5:
                detail += f" (+{len(p) - 5} more)"
            if fail_fast:
                for warning in warnings:
                    print(f"WARN  {warning}", file=sys.stderr)
                raise ArtifactValidationError(
                    f"artifact validation failed at {phase}: {detail}",
                    phase=phase,
                    phase_state=phase_state,
                )
            problems.extend(p)
            continue
        phase_state[phase] = _phase_record(project_slug, phase)

    for warning in warnings:
        print(f"WARN  {warning}", file=sys.stderr)

    if problems:
        detail = "; ".join(problems[:5])
        if len(problems) > 5:
            detail += f" (+{len(problems) - 5} more)"
        raise ArtifactValidationError(
            f"artifact validation failed: {detail}",
            phase_state=phase_state,
        )
    return phase_state or None
