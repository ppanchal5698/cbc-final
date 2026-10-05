"""Pre-render unreadable bid pages so Claude must vision-read them.

The worker writes ``extracted/_visual_pages.json`` after sheetmap + pretakeoff.
Claude Reads the PNGs (or re-calls get_page_image if a cache path is missing)
before trusting bid-docs / empty pretakeoff / no_scope.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz

from cbc.modules.extraction.infrastructure import sheetmap
from cbc.shared import pdfpages, pdfrows
from cbc.shared.paths import repo_root, storage_root
from cbc.shared.storage import atomic_write_json

log = logging.getLogger("cbc.worker")

ROOT = repo_root()
VISUAL_DPI = 200
OCR_TEXT_MAX = 4000  # keep the manifest small; images carry the truth


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_pdf(project_path: str) -> Path:
    """``projects/{slug}/uploads/raw/foo.pdf`` → absolute path under storage."""
    text = str(project_path).replace("\\", "/")
    if text.startswith("projects/"):
        text = text[len("projects/") :]
    return storage_root() / text


def _schedule_force_pages(sheetmap_payload: dict[str, Any]) -> set[tuple[str, int]]:
    """Every schedule / candidate page — forced when pretakeoff found nothing."""
    forced: set[tuple[str, int]] = set()
    for file_row in sheetmap_payload.get("files") or []:
        path = str(file_row.get("path") or "")
        for key in ("schedule_pages", "door_schedule_candidate_pages"):
            for page in file_row.get(key) or []:
                try:
                    forced.add((path, int(page)))
                except (TypeError, ValueError):
                    continue
        for page in file_row.get("pages") or []:
            if not isinstance(page, dict):
                continue
            roles = {str(r).lower() for r in (page.get("roles") or [])}
            if roles & {"door_schedule", "door_schedule_candidate"}:
                try:
                    forced.add((path, int(page["source_page"])))
                except (KeyError, TypeError, ValueError):
                    continue
    return forced


def _ocr_assist(
    pdf: Path,
    page_number: int,
    *,
    has_text_layer: bool | None,
    force: bool = False,
) -> tuple[str | None, bool, str | None]:
    """Optional OCR when the page has no usable text layer (or force for CAD fonts).

    Returns (ocr_text, ocr_used, ocr_status) where ocr_status is None, 'unavailable',
    or 'failed'.
    """
    if has_text_layer is True and not force:
        return None, False, None
    doc = fitz.open(pdf)
    try:
        index = page_number - 1
        if not 0 <= index < doc.page_count:
            return None, False, None
        page = doc[index]
        # Title-only text layers still skip OCR unless forced — body may be outlined.
        if has_text_layer is True and force:
            words = page.get_text("words") or []
            if not pdfrows.text_looks_like_schedule_title_only(page.get_text(), len(words)):
                # Partial text that already looks like a full schedule — skip OCR cost.
                if len(words) >= 40:
                    return None, False, None
        text = pdfrows.ocr_page(doc[index], dpi=VISUAL_DPI)
    finally:
        doc.close()
    if text.startswith("[OCR UNAVAILABLE"):
        return None, False, "unavailable"
    if text.startswith("[OCR FAILED"):
        return None, False, "failed"
    clipped = text.strip()
    if len(clipped) > OCR_TEXT_MAX:
        clipped = clipped[:OCR_TEXT_MAX] + "…"
    return clipped or None, True, None


def _visual_image_dir(slug: str) -> Path:
    """Where a pre-rendered vision page is written: inside the project.

    It used to go to the shared render cache and be recorded relative to the
    repository root. Claude never runs there. Each job clones the project into
    `_scratch/{job}/workspace` and runs with its cwd on that clone, so a
    repo-relative `.cache/pdf-pages/x.png` resolves under the workspace, where
    nothing was ever copied - every mandatory visual `Read` failed and the agent
    fell back to re-rendering, which is the escape hatch, not the path. In
    docker-sandbox mode it is worse: the cache is not mounted at all and the
    container is read-only, so the fallback cannot work either.

    `extracted/` is where extraction output belongs and it is cloned with the
    project, so the same path resolves in both modes.
    """
    return storage_root() / slug / "extracted" / "_visual_pages"


def _project_image_path(image_path: str) -> str:
    """The rendered page as Claude addresses it: `projects/{slug}/...`.

    The same spelling `path` already uses on every row, and the one
    `_resolve_pdf` reverses.
    """
    path = Path(image_path)
    try:
        inside = path.resolve().relative_to(storage_root().resolve())
    except ValueError:
        return str(path).replace("\\", "/")
    return f"projects/{inside.as_posix()}"


def apply_parse_signals(
    sheetmap_payload: dict[str, Any],
    signals_by_path: dict[str, dict[int, dict[str, Any]]] | None,
) -> dict[str, Any]:
    """Re-annotate pages with optional parser verified / block_count signals."""
    if not signals_by_path:
        return sheetmap_payload
    for file_row in sheetmap_payload.get("files") or []:
        path = str(file_row.get("path") or "")
        by_page = signals_by_path.get(path) or signals_by_path.get(Path(path).name) or {}
        pages = list(file_row.get("pages") or [])
        sheetmap.annotate_visual_flags(pages, signals_by_page=by_page)
        file_row["pages"] = pages
        file_row["needs_visual_read_pages"] = sorted(
            {int(p["source_page"]) for p in pages if p.get("needs_visual_read")}
        )
    return sheetmap_payload


def build_visual_pages(
    slug: str,
    *,
    openings_seeded: int = 0,
    signals_by_path: dict[str, dict[int, dict[str, Any]]] | None = None,
    cap: int = sheetmap.VISUAL_PAGE_CAP,
) -> dict[str, Any]:
    """Render capped vision targets and write ``extracted/_visual_pages.json``.

    When pretakeoff seeded 0 openings, every schedule / candidate page is forced
    into the visual set (still subject to ``cap``).
    """
    map_path = sheetmap.sheetmap_path(slug)
    if not map_path.is_file():
        payload = {
            "generated_at": _now(),
            "pages": [],
            "note": "no _sheetmap.json — nothing to pre-render",
        }
        target = sheetmap.visual_pages_path(slug)
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(target, payload)
        return payload

    sheetmap_payload = sheetmap.build_sheetmap(slug)  # no-op rewrite when SHA matches
    sheetmap_payload = apply_parse_signals(sheetmap_payload, signals_by_path)

    force: set[tuple[str, int]] = set()
    if int(openings_seeded or 0) <= 0:
        force = _schedule_force_pages(sheetmap_payload)

    # Persist re-annotated needs_visual_read back onto the sheetmap when parser
    # or pretakeoff force expands the set.
    if signals_by_path or force:
        for file_row in sheetmap_payload.get("files") or []:
            path = str(file_row.get("path") or "")
            pages = list(file_row.get("pages") or [])
            for page in pages:
                if not isinstance(page, dict):
                    continue
                try:
                    source_page = int(page["source_page"])
                except (KeyError, TypeError, ValueError):
                    continue
                if (path, source_page) in force:
                    needs, reasons = sheetmap.page_needs_visual_read(
                        page, pretakeoff_sparse=True
                    )
                    page["needs_visual_read"] = needs or True
                    if "pretakeoff_empty" not in (page.get("visual_reasons") or []):
                        page["visual_reasons"] = list(
                            dict.fromkeys([*(page.get("visual_reasons") or []), "pretakeoff_empty", *reasons])
                        )
            file_row["pages"] = pages
            file_row["needs_visual_read_pages"] = sorted(
                {int(p["source_page"]) for p in pages if isinstance(p, dict) and p.get("needs_visual_read")}
            )
        atomic_write_json(map_path, {**sheetmap_payload, "generated_at": _now()})

    targets = sheetmap.select_visual_targets(sheetmap_payload, force_pages=force, cap=cap)
    rendered: list[dict[str, Any]] = []
    for target in targets:
        path = target["path"]
        source_page = int(target["source_page"])
        pdf = _resolve_pdf(path)
        entry: dict[str, Any] = {
            "path": path,
            "source_page": source_page,
            "reasons": list(target.get("reasons") or []),
            "roles": list(target.get("roles") or []),
            "image_path": None,
            "ocr_text": None,
            "ocr_used": False,
            "ocr_status": None,
        }
        if not pdf.is_file():
            entry["error"] = f"PDF not found: {pdf}"
            rendered.append(entry)
            continue
        try:
            hit = pdfpages.page_image(
                pdf, source_page, dpi=VISUAL_DPI, out_dir=_visual_image_dir(slug)
            )
            entry["image_path"] = _project_image_path(hit["image_path"])
            entry["dpi"] = hit.get("dpi")
            # dpi alone reads as reassuring and is not. A 2448pt sheet at the
            # 1568px vision cap is 46 dpi - 0.64 px/pt - which shows that a
            # table exists and will not yield a single row of it.
            entry["px_per_pt"] = hit.get("px_per_pt")
            entry["legible"] = hit.get("legible")
        except Exception as exc:
            log.warning("visual page render failed %s p%s: %s", path, source_page, exc)
            entry["error"] = str(exc)
            rendered.append(entry)
            continue
        has_layer = target.get("text_poor") is False and (
            target.get("char_count") is not None
            and int(target["char_count"]) >= sheetmap.TEXT_LAYER_MIN_CHARS
        )
        # Prefer explicit has_text_layer from sheetmap when present.
        page_meta: dict[str, Any] | None = None
        for file_row in sheetmap_payload.get("files") or []:
            if file_row.get("path") != path:
                continue
            for page in file_row.get("pages") or []:
                if isinstance(page, dict) and int(page.get("source_page") or 0) == source_page:
                    page_meta = page
                    if page.get("has_text_layer") is not None:
                        has_layer = bool(page["has_text_layer"])
                    break
        reasons = {str(r) for r in (target.get("reasons") or [])}
        roles = {str(r).lower() for r in (target.get("roles") or [])}
        # CAD architectural body fonts often leave only the title in the text
        # layer — force OCR when this is a schedule / pretakeoff-empty target.
        force_ocr = bool(
            openings_seeded <= 0
            and (
                reasons & {"pretakeoff_empty", "text_poor", "no_text_layer", "door_schedule", "door_schedule_candidate"}
                or roles & {"door_schedule", "door_schedule_candidate"}
                or (page_meta or {}).get("text_poor")
            )
        )
        ocr_text, ocr_used, ocr_status = _ocr_assist(
            pdf, source_page, has_text_layer=has_layer, force=force_ocr
        )
        entry["ocr_text"] = ocr_text
        entry["ocr_used"] = ocr_used
        entry["ocr_status"] = ocr_status
        rendered.append(entry)

    payload = {
        "generated_at": _now(),
        "openings_seeded": int(openings_seeded or 0),
        "cap": cap,
        "pages": rendered,
    }
    out = sheetmap.visual_pages_path(slug)
    out.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out, payload)
    log.info(
        "%s visual pages: %d pre-rendered (cap %d, openings_seeded=%s)",
        slug,
        len(rendered),
        cap,
        openings_seeded,
    )
    return payload


def load_visual_pages(slug: str) -> dict[str, Any] | None:
    path = sheetmap.visual_pages_path(slug)
    if not path.is_file():
        return None
    import json

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


# Roles / reasons that gate line_items.json visual_pages_checked.
# Bare "hardware" / "frp" / "finish" are specialist pages — not this checklist.
DOOR_SCHEDULE_VISUAL_ROLES = frozenset({"door_schedule", "door_schedule_candidate"})
# `pretakeoff_empty` is not on this list, though it reads like it belongs. It is
# stamped on *every* forced page when the take-off seeded nothing, so it says the
# run found no openings - not that this sheet is door-schedule work. With it in,
# an FRP / finish sheet joined the door-schedule checklist on the strength of an
# empty take-off, and the block handed to Claude listed a page directly under the
# sentence telling it FRP and finish pages are not on the checklist. A genuine
# schedule page never needs it: `_schedule_force_pages` only forces pages that
# already carry a door-schedule role or the candidate reason.
DOOR_SCHEDULE_VISUAL_REASONS = frozenset({"door_schedule_candidate"})


def is_door_schedule_visual_page(page: dict[str, Any]) -> bool:
    """True when a `_visual_pages.json` row must appear on door_schedule coverage."""
    roles = {str(r).lower() for r in (page.get("roles") or [])}
    reasons = {str(r).lower() for r in (page.get("reasons") or [])}
    return bool(
        roles & DOOR_SCHEDULE_VISUAL_ROLES or reasons & DOOR_SCHEDULE_VISUAL_REASONS
    )


def schedule_visual_keys(slug: str) -> list[tuple[str, int]]:
    """Schedule/candidate ``(path, source_page)`` pairs from the visual manifest.

    `check_extraction` requires every one of these in `visual_pages_checked`,
    uncapped - so the take-off wave must be handed all of them, not just the first
    `MAX_WAVE_PAGES` the sheet map ranked. Shared by that validator (through
    `_visual_manifest_schedule_pages`) and by `extraction_wave`, so the leg is
    never validated on a page it was never handed.
    """
    payload = load_visual_pages(slug)
    hits: list[tuple[str, int]] = []
    for page in (payload.get("pages") or []) if isinstance(payload, dict) else []:
        if not isinstance(page, dict) or not is_door_schedule_visual_page(page):
            continue
        try:
            hits.append((str(page.get("path") or ""), int(page["source_page"])))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(set(hits))



# `verified` is `verify_page`'s score for how much of what the parser claimed
# actually sits on real text. LlamaParse clears it comfortably - 0.849 and 0.913
# on the two sheets of the first real bid - so the picture is the fallback, not
# the first read.
PARSE_TRUSTED_FLOOR = 0.60


def parse_can_answer(page: dict[str, Any]) -> bool:
    """True when the parser read this page well enough to skip the image.

    False for a sheet with no text layer (`verified` is None, reason
    `parser_verified_null`), for a text-poor sheet, and for anything scoring
    below the floor. Those keep the vision path they have always had.
    """
    reasons = {str(r).lower() for r in (page.get("reasons") or [])}
    if "parser_verified_null" in reasons or "text_poor" in reasons:
        return False
    verified = page.get("verified")
    if not isinstance(verified, (int, float)):
        return False
    return float(verified) >= PARSE_TRUSTED_FLOOR


def pages_needing_vision(slug: str) -> list[dict[str, Any]]:
    """Schedule pages the parser could not answer for, so the model must look."""
    payload = load_visual_pages(slug)
    pages = (payload.get("pages") or []) if isinstance(payload, dict) else []
    return [
        page
        for page in pages
        if isinstance(page, dict)
        and is_door_schedule_visual_page(page)
        and not parse_can_answer(page)
    ]


# A row box is about 8pt tall. Cropping it exactly renders a sliver, so the
# region is padded into a band: enough sheet above and below to carry the column
# headers and the neighbouring rows that prove the alignment.
CROP_PAD_Y = 40.0
CROP_PAD_X = 12.0
CROP_ROWS_PER_PAGE = 12
# The vision cap is 1568px on the long edge, so a crop's width sets its
# resolution: 550pt renders at ~2.85 px/pt and reads cleanly, 1900pt at 0.84 and
# does not. A row measured wider than this is handed over in bands rather than as
# one unreadable strip - three of six Wendys rows span nearly the full sheet,
# because a note in the right margin shares their y-band.
CROP_MAX_WIDTH = 550.0
CROP_MAX_BANDS = 2


def seeded_row_regions(slug: str) -> dict[int, list[tuple[str, list[float]]]]:
    """Ready-to-crop regions for seeded rows, keyed by page.

    The seed measures every row it reads before the model sees anything, and the
    checklist then told the model to "crop that rectangle" without ever saying
    what it was. So it hunted: on one bid, six crops of a floor plan and five of
    a schedule sheet whose rows were already boxed in the artifact next to it.

    Naming the rectangle costs one line per row and removes the hunt.
    """
    from cbc.shared.pass_files import read_json
    from cbc.shared.storage import project_dir

    payload = read_json(project_dir(slug) / "extracted" / "line_items.json")
    if isinstance(payload, dict):
        rows = payload.get("openings") or payload.get("lines") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        return {}

    out: dict[int, list[tuple[str, list[float]]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        bbox = row.get("bbox")
        page = row.get("source_page")
        if not (isinstance(page, int) and isinstance(bbox, list) and len(bbox) == 4):
            continue
        try:
            x0, y0, x1, y1 = (float(v) for v in bbox)
        except (TypeError, ValueError):
            continue
        mark = str(row.get("door_number") or row.get("mark") or "?")
        left, top = x0 - CROP_PAD_X, round(y0 - CROP_PAD_Y, 1)
        bottom, right = round(y1 + CROP_PAD_Y, 1), x1 + CROP_PAD_X
        for band in range(CROP_MAX_BANDS):
            start = left + band * CROP_MAX_WIDTH
            # A sliver left over past the last full band is one column edge, not
            # a reading - the padding alone accounts for most of it.
            if right - start < (CROP_MAX_WIDTH / 4 if band else 1):
                break
            out.setdefault(page, []).append(
                (
                    mark if band == 0 else f"{mark} (cont.)",
                    [
                        round(start, 1),
                        top,
                        round(min(start + CROP_MAX_WIDTH, right), 1),
                        bottom,
                    ],
                )
            )
    return out


# Handing is the one field that is genuinely a picture.
#
# It is read off the door swing on a floor plan and printed as text nowhere, so
# no amount of parsing produces it - which is why the take-off went hunting. On
# one 24-page bid it rendered the same floor plan six times looking for doors it
# could already have been pointed at: the marks are printed on the plan, in the
# text layer, as their own small tags.
#
# 300pt renders at about 4.2 px/pt against the 1568px cap, which is enough to
# read a swing arc and the leaf. Marks cluster - four doors of that bid sit
# inside one 300pt square - so overlapping crops are merged and one picture
# answers several openings.
HANDING_CROP = 300.0
HANDING_MAX_REGIONS = 8


def _mark_positions(page: "fitz.Page", marks: set[str]) -> list[tuple[str, list[float]]]:
    """Where each opening's mark is printed on this sheet, as its own tag.

    Whole-cell matches only. A door tag is its own cell; `05` inside `5'-0"` or a
    dimension string is not a door, and matching loosely would send the estimator
    to a random dimension line with the confidence of a measurement.
    """
    found: list[tuple[str, list[float]]] = []
    for row in pdfrows.rows_from_words(page):
        for cell, box in zip(row.get("cells") or [], row.get("cell_boxes") or []):
            text = (cell or "").strip()
            if text in marks:
                found.append((text, [float(v) for v in box]))
    return found


def _merge(
    spots: list[tuple[str, list[float]]], bounds: tuple[float, float]
) -> list[dict[str, Any]]:
    """Square crops around each mark, merged where they overlap.

    Kept inside the sheet: a mark near an edge centres a box that runs off it,
    and a crop with a negative corner renders as somewhere else entirely.

    ponytail: O(n^2) over the marks on one sheet - a schedule has tens, not
    thousands. Sort-and-sweep if a bid ever arrives with hundreds.
    """
    width, height = bounds
    regions: list[dict[str, Any]] = []
    for mark, box in spots:
        half = HANDING_CROP / 2
        cx = min(max((box[0] + box[2]) / 2, half), max(width - half, half))
        cy = min(max((box[1] + box[3]) / 2, half), max(height - half, half))
        rect = [
            max(cx - half, 0.0),
            max(cy - half, 0.0),
            min(cx + half, width),
            min(cy + half, height),
        ]
        for region in regions:
            other = region["region"]
            if rect[0] < other[2] and other[0] < rect[2] and rect[1] < other[3] and other[1] < rect[3]:
                # Keep the box the size it was; a merged crop that grows stops
                # being legible, which is the whole point of the size.
                region["marks"].append(mark)
                break
        else:
            regions.append({"region": rect, "marks": [mark]})
    for region in regions:
        region["region"] = [round(v, 1) for v in region["region"]]
        region["marks"] = sorted(set(region["marks"]))
    return regions


def handing_regions(slug: str) -> list[dict[str, Any]]:
    """Floor-plan crops showing the swing of every opening still missing handing.

    Returns `[{path, page, region, marks}]`, ordered by how many openings each
    crop answers, so the first picture is the one worth taking.
    """
    from cbc.shared.pass_files import read_json
    from cbc.shared.storage import project_dir

    root = project_dir(slug)
    payload = read_json(root / "extracted" / "line_items.json")
    if isinstance(payload, dict):
        openings = payload.get("openings") or payload.get("lines") or []
    elif isinstance(payload, list):
        openings = payload
    else:
        return []

    marks = {
        str(o.get("door_number") or o.get("mark") or "").strip()
        for o in openings
        if isinstance(o, dict)
        and not str(o.get("handing") or "").strip()
        and o.get("in_scope") is not False
    }
    marks.discard("")
    if not marks:
        return []

    sheetmap = read_json(root / "extracted" / "_sheetmap.json")
    if not isinstance(sheetmap, dict):
        return []

    out: list[dict[str, Any]] = []
    for entry in sheetmap.get("files") or []:
        pages = [
            page.get("source_page")
            for page in (entry.get("pages") or [])
            if "floor_plan" in {str(r).lower() for r in (page.get("roles") or [])}
        ]
        if not pages:
            continue
        try:
            document = fitz.open(_resolve_pdf(str(entry.get("path") or "")))
        except Exception:  # a missing upload is not worth failing a prompt over
            continue
        try:
            for number in sorted(p for p in pages if isinstance(p, int)):
                if not 0 <= number - 1 < document.page_count:
                    continue
                page = document[number - 1]
                spots = _mark_positions(page, marks)
                for region in _merge(spots, (page.rect.width, page.rect.height)):
                    out.append(
                        {
                            "path": entry.get("path"),
                            "page": number,
                            "region": region["region"],
                            "marks": region["marks"],
                        }
                    )
        finally:
            document.close()

    # The fewest pictures that show every opening. A mark is usually printed on
    # several sheets, so listing every place it appears reproduces the hunt this
    # exists to end - on one real bid it was eight crops where the first one
    # already showed all four doors.
    out.sort(key=lambda r: (-len(r["marks"]), r["page"]))
    covered: set[str] = set()
    chosen: list[dict[str, Any]] = []
    for region in out:
        if set(region["marks"]) - covered:
            covered.update(region["marks"])
            chosen.append(region)
        if covered >= marks:
            break
    return chosen[:HANDING_MAX_REGIONS]


def prompt_checklist(slug: str) -> str:
    """Injected into the extract prompt: read the parse, look only where it failed.

    This block used to say "Read the `image_path` PNG first" and "do **not**
    prefer bid-docs / extract_text as the first read on these pages". LlamaParse
    verifies at 0.85-0.91 on those sheets and carries per-cell boxes, and the
    instruction cost real runs: on one 24-page bid the take-off rendered
    two sheets twenty-four times, hit its 80-turn cap and produced a single
    patch, while the door schedule sat parsed in Mongo one `get_page_blocks`
    call away.

    Only pages the parser could not answer for are listed now.
    """
    needs_vision = pages_needing_vision(slug)

    lines = [
        "**Read the parse before you render anything.** This bid set is parsed:",
        "`get_page_blocks(document_id, page)` returns blocks with `text`, a `bbox`,",
        "and on tables the `cells` and `cell_boxes`. A schedule row you can read in",
        "`cells` is a row you do not need a picture of - and the cell box is a",
        "better citation than anything you could crop by eye.",
        "",
        "`search_blocks` finds the page; `get_page_blocks` reads it.",
        "",
        "**Look at the sheet when, and only when:**",
        "- the field is **handing** - it is read off the door swing on a floor plan",
        "  and printed as text nowhere, so it is always a vision read. The crops",
        "  are listed below: do not go looking for the plan;",
        "- the page is listed below, where the parser found no text layer to verify",
        "  against, or scored too low to trust;",
        "- `get_page_blocks` returns zero blocks on a page the sheet map says",
        "  carries a schedule.",
        "",
    ]

    if needs_vision:
        lines += [
            "**These pages need your eyes - the parser could not read them.**",
            "",
            "A full architectural sheet renders at about 0.6 px/pt against the",
            "1568px vision cap: enough to see *that* a schedule is there, nowhere",
            "near enough to read a row. Crop with",
            "`get_page_image(page, region=[x0,y0,x1,y1])` over about 350-550pt.",
            "More `dpi` does nothing - the cap is on pixels. The reply carries",
            "`px_per_pt` and `legible`; read those rather than guessing from the",
            "picture. Do not re-crop blind - the rectangles below are measured.",
            "",
        ]
        for page in needs_vision:
            reasons = ", ".join(str(r) for r in (page.get("reasons") or []) if r) or "unreadable"
            image = page.get("image_path") or "(render failed - call get_page_image)"
            lines.append(
                f"- `{page.get('path')}` page {page.get('source_page')}: "
                f"reasons=[{reasons}]; image=`{image}`"
            )
        lines.append("")
    else:
        lines += [
            "**No schedule page on this bid needs a vision read.** The parser",
            "verified every one of them. Cite the block you read.",
            "",
        ]

    swings = handing_regions(slug)
    if swings:
        lines += [
            "**Handing: these crops show the swings.** Each opening's mark is",
            "printed on the plan as its own tag, so the rectangle around it has",
            "been measured for you. This is the fewest pictures that cover every",
            "opening still missing handing - usually one.",
            "",
        ]
        for spot in swings:
            covers = ", ".join(spot["marks"])
            lines.append(
                f"- doors {covers}: `get_page_image({spot['page']}, region={spot['region']})`"
            )
        lines += [
            "",
            "Read the swing off the arc and the leaf. If a door is not legible in",
            "its crop, say so and leave `handing` null with `handing_missing` - a",
            "guessed hand is a door that opens the wrong way on site.",
            "",
        ]

    regions = seeded_row_regions(slug)
    if regions:
        lines += [
            "**When you do need to look at a seeded row, the rectangle is already",
            "measured.** Paste it - do not search for it by eye:",
            "",
        ]
        for page in sorted(regions):
            for mark, region in regions[page][:CROP_ROWS_PER_PAGE]:
                lines.append(
                    f"- door {mark}: `get_page_image({page}, region={region})`"
                )
            extra = len(regions[page]) - CROP_ROWS_PER_PAGE
            if extra > 0:
                lines.append(
                    f"- ...and {extra} more row(s) on page {page}, each with a `bbox`"
                    " in the seeded artifact."
                )
        lines += [
            "",
            "A row you can read in `cells` still does not need a picture at all.",
            "",
        ]

    lines += [
        "Record what you checked with **one patch**, before save / no_scope - the",
        "artifact is seeded, so this is a patch and not a whole-file write:",
        "",
        "    propose_patch(project, 'extracted/line_items.json', [{",
        '      "op": "set", "path": "visual_pages_checked",',
        '      "value": [{"path": …, "source_page": …, "image_path": …,',
        '                 "finding": "what you found"}, …]}])',
        "",
        "A page you answered from parsed blocks belongs in that list too - give the",
        "block number in place of an `image_path`. The gate is that you checked the",
        "page, not that you rendered it.",
        "",
        "`visual_pages_checked` is the one top-level path a patch may set. A row",
        "reading is still `openings/<door number>/<field>`.",
    ]
    return "\n".join(lines)
