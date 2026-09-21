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


def apply_mineru_signals(
    sheetmap_payload: dict[str, Any],
    mineru_by_path: dict[str, dict[int, dict[str, Any]]] | None,
) -> dict[str, Any]:
    """Re-annotate pages with optional MinerU verified / block_count signals."""
    if not mineru_by_path:
        return sheetmap_payload
    for file_row in sheetmap_payload.get("files") or []:
        path = str(file_row.get("path") or "")
        by_page = mineru_by_path.get(path) or mineru_by_path.get(Path(path).name) or {}
        pages = list(file_row.get("pages") or [])
        sheetmap.annotate_visual_flags(pages, mineru_by_page=by_page)
        file_row["pages"] = pages
        file_row["needs_visual_read_pages"] = sorted(
            {int(p["source_page"]) for p in pages if p.get("needs_visual_read")}
        )
    return sheetmap_payload


def build_visual_pages(
    slug: str,
    *,
    openings_seeded: int = 0,
    mineru_by_path: dict[str, dict[int, dict[str, Any]]] | None = None,
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
    sheetmap_payload = apply_mineru_signals(sheetmap_payload, mineru_by_path)

    force: set[tuple[str, int]] = set()
    if int(openings_seeded or 0) <= 0:
        force = _schedule_force_pages(sheetmap_payload)

    # Persist re-annotated needs_visual_read back onto the sheetmap when MinerU
    # or pretakeoff force expands the set.
    if mineru_by_path or force:
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


# Roles / reasons that gate door_schedule.json visual_pages_checked.
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


def prompt_checklist(slug: str) -> str:
    """Block injected into the extract prompt listing mandatory vision pages.

    Only schedule / candidate pages — same filter as door_schedule validation.
    FRP / finish / bare-hardware MinerU-null sheets are omitted here.
    """
    payload = load_visual_pages(slug)
    if not payload:
        return ""
    pages = [
        p
        for p in (payload.get("pages") or [])
        if isinstance(p, dict) and is_door_schedule_visual_page(p)
    ]
    if not pages:
        return ""
    lines = [
        "**Mandatory visual reads (worker pre-rendered).** These pages are",
        "door schedule / schedule-candidate sheets with weak text. For each",
        "row: `Read` the `image_path` PNG first (or call `get_page_image` if",
        "the file is missing). Do **not** prefer bid-docs / extract_text as the",
        "first read on these pages. FRP / finish / bare hardware vision pages",
        "are specialist work — not this checklist.",
        "",
        "**These are triage images, not readable ones.** A full architectural",
        "sheet renders at roughly 0.6 px/pt against the 1568px vision cap —",
        "enough to see *that* a schedule is on the page, nowhere near enough to",
        "read a row. To read one, crop: `get_page_image(page, region=[x0,y0,x1,y1])`",
        "over about 350–550pt. Raising `dpi` does nothing; the cap is on pixels,",
        "so the only lever is a smaller region. The reply carries `px_per_pt`",
        "and `legible` — check them instead of guessing from the picture.",
        "",
        "**On a page with a text layer, read it before you render anything.**",
        "`parse_door_openings` or `extract_tables` return rows *with bboxes*,",
        "which is both cheaper and more precise than reading pixels.",
        "",
        "Record them with **one patch**, before save / no_scope — the artifact is",
        "seeded, so this is a patch and not a whole-file write:",
        "",
        "    propose_patch(project, 'extracted/door_schedule.json', [{",
        '      "op": "set", "path": "visual_pages_checked",',
        '      "value": [{"path": …, "source_page": …, "image_path": …,',
        '                 "finding": "what the image showed"}, …]}])',
        "",
        "`visual_pages_checked` is the one top-level path a patch may set. A row",
        "reading is still `openings/<door number>/<field>`.",
        "",
    ]
    for page in pages:
        reasons = ", ".join(str(r) for r in (page.get("reasons") or []) if r) or "unreadable"
        image = page.get("image_path") or "(render failed — call get_page_image)"
        lines.append(
            f"- `{page.get('path')}` page {page.get('source_page')}: "
            f"reasons=[{reasons}]; image=`{image}`"
        )
    return "\n".join(lines)
