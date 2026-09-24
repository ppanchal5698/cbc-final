"""Deterministic sheet map written before a take-off prompt is built (B-11).

`find_sheets` is the same work on every extract job. The worker runs it once,
merges schedule-marker pages from `parse_schedule.find_schedule_pages`, and
writes `extracted/_sheetmap.json` so Claude reads the ranked pages instead of
searching the set again.

Pages carry `roles` (title / door_schedule / hardware / div08_specs /
floor_plan / div10 / frp / finish) so each subagent receives only the page
lists it needs. Take-off follows the CBC 95% ladder: door schedule → Div 08
hardware schedule → Div 08 door/frame specs → floor plans → Div 10 / FRP.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cbc.shared import pdfpages
from cbc.shared.paths import repo_root, storage_root
from cbc.shared.storage import atomic_write_json

ROOT = repo_root()
SHEETMAP_REL = "extracted/_sheetmap.json"
TRIAGE_REL = "extracted/_triage.json"
SHEETMAP_JOB_TYPES = frozenset(
    {
        "extract_bid_set",
        "rerun_extraction",
        "ingest_addendum",
        "run_full_pipeline",
    }
)

# Term / marker → role tags for per-agent page slices.
ROLE_TERM_HINTS: dict[str, tuple[str, ...]] = {
    "title": ("title block", "cover sheet", "drawing index", "project no", "architect"),
    "door_schedule": ("door schedule", "door type", "opening schedule", "frame schedule"),
    "hardware": ("hardware", "hw set", "hardware set", "lockset", "hardware groups"),
    "div08_specs": (
        "division 08",
        "doors and frames",
        "hollow metal",
        "finish hardware",
        "wood doors",
    ),
    "floor_plan": ("floor plan", "enlarged plan", "door plan", "first floor", "second floor"),
    "div10": (
        "toilet partition",
        "toilet accessories",
        "restroom accessories",
        "hand dryer",
        "washroom",
        "division 10",
    ),
    "frp": ("frp", "fiberglass", "wall panel", "j-channel", "cove base"),
    "finish": ("finish schedule", "room finish", "finish"),
}

# CAD title-block sheet numbers that commonly carry door/window schedules when
# the schedule body is outlined text (invisible to get_text). Prefer primary
# schedule sheets (A2.x schedules, A3.0, A4.0, A5.0, A7–A10) over word-count noise.
# Detail minors (A4.1, A5.1, …) are candidates only when they do not look like
# storefront / window details — ID alone must not hard-ban a real schedule.
DOOR_SCHEDULE_SHEET_ID_RE = re.compile(
    r"^A(?:2\.\d+|3\.0|4\.0|5\.0|7\.\d+|8\.0|9\.\d+|10\.0)$",
    re.IGNORECASE,
)
# Non-zero sheet minors that are often details; soft-exclude on storefront cues.
DETAIL_SHEET_ID_RE = re.compile(r"^A\d+\.[1-9]\d*$", re.IGNORECASE)
STOREFRONT_DETAIL_HINTS = (
    "storefront",
    "curtain wall",
    "window schedule",
    "window type",
    "glazing elev",
    "exterior elevation detail",
    "aluminum storefront",
)
# Below this many extractable characters a sheet is treated as text-poor CAD.
TEXT_POOR_CHAR_THRESHOLD = 500
# Matches pdfrows.has_text_layer default — below this, treat as no usable text layer.
TEXT_LAYER_MIN_CHARS = 40
# High-value roles that force a vision read when text looks weak / empty.
HIGH_VALUE_VISUAL_ROLES = frozenset(
    {
        "door_schedule",
        "door_schedule_candidate",
        "hardware",
        "frp",
        "div10",
        "floor_plan",
        "div08_specs",
    }
)
# Cap pre-rendered vision targets per bid (token + disk budget).
VISUAL_PAGE_CAP = 24
# Priority when capping: lower index = keep first.
_VISUAL_ROLE_PRIORITY = (
    "door_schedule",
    "door_schedule_candidate",
    "hardware",
    "frp",
    "div10",
    "div08_specs",
    "floor_plan",
    "text_poor",
)
# Floor-plan sheet IDs are a hint only — ROLE_TERM_HINTS also catch "first floor".
FLOOR_PLAN_SHEET_ID_RE = re.compile(r"^A1\.\d+$", re.IGNORECASE)
VISUAL_PAGES_REL = "extracted/_visual_pages.json"
# Sentinel: parser signal absent (distinct from verified=None for image-only pages).
_NO_SIGNAL = object()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sheetmap_path(slug: str) -> Path:
    return storage_root() / slug / SHEETMAP_REL


def triage_path(slug: str) -> Path:
    return storage_root() / slug / TRIAGE_REL


def load_triage(slug: str) -> dict[str, Any]:
    """Claude's page triage, or {} when it has not run.

    Kept in its own file rather than written into `_sheetmap.json`, because
    `build_sheetmap` regenerates that file wholesale whenever a source SHA moves
    or `force=True` - anything Claude wrote into it would be silently erased on
    the next `prepare()`. The sidecar is the record; the sheetmap unions it in.
    """
    target = triage_path(slug)
    if not target.is_file():
        return {}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _apply_triage(slug: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Attach Claude's roles to each page as `triage_roles`, read fresh each time.

    Separate from `roles` on purpose. `roles` stays exactly what the deterministic
    pass derived, so the two are never confused and a re-run of triage cannot
    leave a stale role behind: `triage_roles` is replaced from the sidecar on
    every build rather than merged into a field that persists.
    """
    triage = load_triage(slug)
    by_page = triage.get("pages") if isinstance(triage.get("pages"), dict) else {}
    if not by_page:
        return payload
    for file_row in payload.get("files") or []:
        path = file_row.get("path")
        for page in file_row.get("pages") or []:
            key = f"{path}#{page.get('source_page')}"
            entry = by_page.get(key) or {}
            roles = [str(r).lower() for r in (entry.get("roles") or [])]
            page["triage_roles"] = roles
            if entry.get("alternate"):
                page["alternate"] = entry["alternate"]
    return payload


def visual_pages_path(slug: str) -> Path:
    return storage_root() / slug / VISUAL_PAGES_REL


def _has_text_layer(char_count: int | None) -> bool | None:
    """None when char_count was not measured; otherwise pdfrows.has_text_layer rule."""
    if char_count is None:
        return None
    return int(char_count) >= TEXT_LAYER_MIN_CHARS


def visual_reasons_for_page(
    *,
    char_count: int | None,
    roles: list[str] | set[str] | None,
    text_poor: bool = False,
    parser_verified: Any = _NO_SIGNAL,
    parser_block_count: int | None = None,
    pretakeoff_sparse: bool = False,
) -> list[str]:
    """Why this page must be vision-read (empty list ⇒ text path is enough).

    Pass ``parser_verified=None`` when the parser reported no text layer to compare;
    omit / pass ``_NO_SIGNAL`` when there is no parser signal for the page.
    """
    role_set = {str(r).lower() for r in (roles or [])}
    reasons: list[str] = []
    has_layer = _has_text_layer(char_count)
    poor = bool(text_poor) or (
        char_count is not None and int(char_count) < TEXT_POOR_CHAR_THRESHOLD
    )
    if has_layer is False:
        reasons.append("no_text_layer")
    if poor:
        reasons.append("text_poor")
    if parser_verified is not _NO_SIGNAL:
        if parser_verified is None:
            reasons.append("parser_verified_null")
        if parser_block_count is not None and int(parser_block_count) == 0:
            reasons.append("parser_empty_blocks")
    high_value = bool(role_set & HIGH_VALUE_VISUAL_ROLES)
    if high_value and pretakeoff_sparse:
        reasons.append("pretakeoff_empty")
    if high_value and (poor or has_layer is False or pretakeoff_sparse):
        for role in _VISUAL_ROLE_PRIORITY:
            if role in role_set and role != "text_poor":
                reasons.append(role)
                break
    seen: set[str] = set()
    ordered: list[str] = []
    for reason in reasons:
        if reason not in seen:
            seen.add(reason)
            ordered.append(reason)
    return ordered


def page_needs_visual_read(
    page: dict[str, Any],
    *,
    signals: dict[str, Any] | None = None,
    pretakeoff_sparse: bool = False,
) -> tuple[bool, list[str]]:
    """Return (needs_visual_read, reasons) for one sheetmap page dict."""
    signals = signals or {}
    verified = signals["verified"] if "verified" in signals else _NO_SIGNAL
    block_count = signals.get("block_count")
    roles = list(page.get("roles") or [])
    char_count = page.get("char_count")
    text_poor = bool(page.get("text_poor")) or (
        char_count is not None and int(char_count) < TEXT_POOR_CHAR_THRESHOLD
    )
    reasons = visual_reasons_for_page(
        char_count=int(char_count) if char_count is not None else None,
        roles=roles,
        text_poor=text_poor,
        parser_verified=verified,
        parser_block_count=int(block_count) if block_count is not None else None,
        pretakeoff_sparse=pretakeoff_sparse,
    )
    return bool(reasons), reasons


def _visual_priority_key(page: dict[str, Any]) -> tuple[int, int, int]:
    roles = {str(r).lower() for r in (page.get("roles") or [])}
    role_rank = len(_VISUAL_ROLE_PRIORITY)
    for index, role in enumerate(_VISUAL_ROLE_PRIORITY):
        if role in roles or role in (page.get("visual_reasons") or []):
            role_rank = index
            break
    return (
        role_rank,
        0 if page.get("needs_visual_read") else 1,
        int(page.get("source_page") or 0),
    )


def select_visual_targets(
    sheetmap: dict[str, Any],
    *,
    force_pages: set[tuple[str, int]] | None = None,
    cap: int = VISUAL_PAGE_CAP,
) -> list[dict[str, Any]]:
    """Capped list of {path, source_page, roles, reasons} for pre-render.

    ``force_pages`` is a set of (path, source_page) that must be included when
    present in the sheetmap (e.g. schedule candidates after empty pretakeoff).
    """
    force_pages = force_pages or set()
    candidates: list[dict[str, Any]] = []
    for file_row in sheetmap.get("files") or []:
        path = str(file_row.get("path") or "")
        for page in file_row.get("pages") or []:
            if not isinstance(page, dict):
                continue
            try:
                source_page = int(page["source_page"])
            except (KeyError, TypeError, ValueError):
                continue
            forced = (path, source_page) in force_pages
            needs = bool(page.get("needs_visual_read")) or forced
            if not needs:
                continue
            reasons = list(page.get("visual_reasons") or [])
            if forced and "pretakeoff_empty" not in reasons:
                reasons = [*reasons, "pretakeoff_empty"]
            candidates.append(
                {
                    "path": path,
                    "source_page": source_page,
                    "roles": list(page.get("roles") or []),
                    "reasons": reasons,
                    "needs_visual_read": True,
                    "visual_reasons": reasons,
                    "char_count": page.get("char_count"),
                    "text_poor": page.get("text_poor"),
                }
            )
    candidates.sort(key=_visual_priority_key)
    if cap > 0:
        return candidates[:cap]
    return candidates


def annotate_visual_flags(
    pages: list[dict[str, Any]],
    *,
    signals_by_page: dict[int, dict[str, Any]] | None = None,
    pretakeoff_sparse: bool = False,
) -> list[dict[str, Any]]:
    """Mutate/return pages with needs_visual_read + visual_reasons filled in."""
    signals_by_page = signals_by_page or {}
    for page in pages:
        if not isinstance(page, dict):
            continue
        try:
            source_page = int(page["source_page"])
        except (KeyError, TypeError, ValueError):
            continue
        needs, reasons = page_needs_visual_read(
            page,
            signals=signals_by_page.get(source_page),
            pretakeoff_sparse=pretakeoff_sparse
            and bool(
                {str(r).lower() for r in (page.get("roles") or [])}
                & {"door_schedule", "door_schedule_candidate", "hardware"}
            ),
        )
        page["has_text_layer"] = _has_text_layer(
            int(page["char_count"]) if page.get("char_count") is not None else None
        )
        page["needs_visual_read"] = needs
        page["visual_reasons"] = reasons
    return pages


def _load_parse_schedule():
    path = (
        ROOT
        / ".claude"
        / "skills"
        / "extract-door-schedule"
        / "scripts"
        / "parse_schedule.py"
    )
    name = "cbc_parse_schedule"
    # Cached on the file's mtime, not on the name alone.
    #
    # The worker is long-lived and `.claude` is a bind mount, so an edit to the
    # parser lands on disk under a process that has already imported it. A
    # `name in sys.modules` cache then serves the pre-edit module for the life
    # of the worker, and the edit looks like it did nothing: a real fix to the
    # schedule row parser was applied, a bid was re-run, and the output came
    # back byte-identical with no error anywhere to explain it.
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:  # gone or unreadable - let the import below report it
        stamp = None
    cached = sys.modules.get(name)
    if cached is not None and getattr(cached, "_cbc_loaded_from", None) == stamp:
        return cached

    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    module._cbc_loaded_from = stamp
    return module


def _find_sheets(file_path: str) -> dict[str, Any]:
    from _runtime import load_server

    return load_server("pdf-tools").find_sheets(file_path)


def _roles_for_page(
    terms: dict[str, Any] | None,
    markers: list[str],
    *,
    sheet_ids: list[str] | None = None,
    char_count: int | None = None,
) -> list[str]:
    """Assign role tags from find_sheets term hits and schedule/title markers."""
    blob_parts: list[str] = []
    for key, count in (terms or {}).items():
        if count:
            blob_parts.append(str(key).lower())
    for marker in markers or []:
        blob_parts.append(str(marker).lower())
    blob = " ".join(blob_parts)
    roles: set[str] = set()
    for role, hints in ROLE_TERM_HINTS.items():
        if any(hint in blob for hint in hints):
            roles.add(role)
    upper_markers = {str(m).upper() for m in (markers or [])}
    if upper_markers & {
        "DOOR SCHEDULE",
        "DOOR TYPE SCHEDULE",
        "FRAME SCHEDULE",
        "OPENING SCHEDULE",
        "DOOR AND FRAME SCHEDULE",
        "DOOR & FRAME SCHEDULE",
        "DOOR HARDWARE SCHEDULE",
        "HW SCHEDULE",
    }:
        roles.add("door_schedule")
    if upper_markers & {
        "HARDWARE GROUPS",
        "HARDWARE SCHEDULE",
        "FINISH HARDWARE",
        "DOOR HARDWARE SCHEDULE",
        "HW SCHEDULE",
    }:
        roles.add("hardware")
    if upper_markers & {"FINISH SCHEDULE", "ROOM FINISH SCHEDULE"}:
        roles.add("finish")
    if any("FRP" in m or "FIBERGLASS" in m or "WALL PANEL" in m for m in upper_markers):
        roles.add("frp")
    if any("TITLE" in m or "COVER" in m or "INDEX" in m for m in upper_markers):
        roles.add("title")
    if any(
        "FLOOR PLAN" in m or "ENLARGED PLAN" in m or "DOOR PLAN" in m for m in upper_markers
    ):
        roles.add("floor_plan")
    if any(
        "TOILET" in m or "PARTITION" in m or "ACCESSOR" in m or "HAND DRYER" in m or "DIVISION 10" in m
        for m in upper_markers
    ):
        roles.add("div10")
    if any("DIVISION 08" in m or "DOORS AND FRAMES" in m for m in upper_markers):
        roles.add("div08_specs")

    # Sheet-number heuristics for CAD text-poor drawings: A2.2 / A4.0 / A7.x etc.
    # often hold the schedule even when "DOOR SCHEDULE" never appears in get_text.
    ids = [str(s) for s in (sheet_ids or []) if s]
    text_poor = char_count is not None and int(char_count) < TEXT_POOR_CHAR_THRESHOLD
    if text_poor and ids:
        roles.add("text_poor")
    term_blob = " ".join(str(t).lower() for t in (terms or {}))
    storefront_like = any(hint in term_blob for hint in STOREFRONT_DETAIL_HINTS)
    for sheet_id in ids:
        if DOOR_SCHEDULE_SHEET_ID_RE.match(sheet_id):
            if "door_schedule" not in roles:
                roles.add("door_schedule_candidate")
            roles.add("hardware")  # HW legend usually shares the sheet
        elif (
            text_poor
            and DETAIL_SHEET_ID_RE.match(sheet_id)
            and not storefront_like
            and "door_schedule" not in roles
        ):
            # Soft path: A4.1-style IDs can still be schedules; skip storefront cues.
            roles.add("door_schedule_candidate")
        if FLOOR_PLAN_SHEET_ID_RE.match(sheet_id) and "floor_plan" not in roles:
            roles.add("floor_plan")
    return sorted(roles)


def _merge_pages(ranked: dict[str, Any], markers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_marker = {int(row["source_page"]): list(row.get("markers") or []) for row in markers}
    pages: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in ranked.get("pages") or []:
        source_page = int(row["source_page"])
        seen.add(source_page)
        terms = row.get("terms") or {}
        found = by_marker.get(source_page) or []
        sheet_ids = list(row.get("sheet_ids") or [])
        char_count = row.get("char_count")
        char_int = int(char_count) if char_count is not None else None
        roles = _roles_for_page(
            terms if isinstance(terms, dict) else {},
            found,
            sheet_ids=sheet_ids,
            char_count=char_int,
        )
        why_parts: list[str] = []
        if found:
            why_parts.extend(str(m) for m in found)
        elif terms:
            why_parts.extend(str(t) for t in terms)
        if sheet_ids:
            why_parts.append("sheet " + "/".join(sheet_ids))
        text_poor = char_int is not None and char_int < TEXT_POOR_CHAR_THRESHOLD
        page = {
            "source_page": source_page,
            "score": row.get("score") or 0,
            "terms": terms,
            "kind": "schedule" if found else "ranked",
            "why": ", ".join(why_parts),
            "markers": found,
            "roles": roles,
            "sheet_ids": sheet_ids,
            "char_count": char_count,
            "text_poor": text_poor or "text_poor" in roles,
            "has_text_layer": _has_text_layer(char_int),
        }
        needs, reasons = page_needs_visual_read(page)
        page["needs_visual_read"] = needs
        page["visual_reasons"] = reasons
        pages.append(page)
    for source_page, found in sorted(by_marker.items()):
        if source_page in seen:
            continue
        roles = _roles_for_page({}, found)
        page = {
            "source_page": source_page,
            "score": 0,
            "terms": {},
            "kind": "schedule",
            "why": ", ".join(found),
            "markers": found,
            "roles": roles,
            "sheet_ids": [],
            "char_count": None,
            "text_poor": False,
            "has_text_layer": None,
        }
        needs, reasons = page_needs_visual_read(page)
        page["needs_visual_read"] = needs
        page["visual_reasons"] = reasons
        pages.append(page)
    # A page carrying a real schedule marker outranks any page that merely uses
    # the words a lot. Sorted on score alone, an accessibility details sheet with
    # 30 uses of "door" led the map on a bid whose Division 08 scope was nil.
    # Door-schedule candidates (sheet-ID heuristics) outrank pure word counts.
    pages.sort(
        key=lambda p: (
            0 if p.get("kind") == "schedule" else 1,
            0 if "door_schedule" in (p.get("roles") or []) else 1,
            0 if "door_schedule_candidate" in (p.get("roles") or []) else 1,
            -int(p.get("score") or 0),
            int(p["source_page"]),
        )
    )
    return pages


def pages_for_roles(sheetmap: dict[str, Any], *roles: str) -> list[dict[str, Any]]:
    """Flatten file/page hits that carry any of the requested roles."""
    wanted = {r.lower() for r in roles if r}
    hits: list[dict[str, Any]] = []
    for file_row in sheetmap.get("files") or []:
        path = file_row.get("path")
        for page in file_row.get("pages") or []:
            # Claude's triage roles count the same as the derived ones. A page it
            # identified that the term heuristics missed is exactly the case
            # triage exists for; leaving it out of the lookup would make the
            # sidecar decorative.
            page_roles = {str(r).lower() for r in (page.get("roles") or [])}
            page_roles |= {str(r).lower() for r in (page.get("triage_roles") or [])}
            if wanted and not (page_roles & wanted):
                continue
            hits.append(
                {
                    "path": path,
                    "source_page": page.get("source_page"),
                    "roles": sorted(page_roles),
                    "kind": page.get("kind"),
                    "why": page.get("why"),
                }
            )
    return hits


def _project_relative(slug: str, pdf: Path) -> str:
    """The path a pdf-tools call takes, whole.

    This used to be `uploads/raw/<name>`, so every caller rebuilt the project
    directory in front of it by hand. One run typed `dunkin_donots_remodel` and
    three searches - the ones hunting for the door schedule - came back "PDF not
    found" against a set that was there all along. Nothing should have to retype
    a slug it was already given.
    """
    return f"projects/{slug}/uploads/raw/{pdf.name}"


def _file_entry(slug: str, pdf: Path) -> dict[str, Any]:
    path = str(pdf)
    ranked = _find_sheets(path)
    parse = _load_parse_schedule()
    markers = list(parse.find_schedule_pages(path) or [])
    pages = _merge_pages(ranked, markers)
    schedule_pages = [p["source_page"] for p in pages if p.get("kind") == "schedule"]
    candidate_pages = [
        p["source_page"]
        for p in pages
        if "door_schedule_candidate" in (p.get("roles") or [])
        or "door_schedule" in (p.get("roles") or [])
    ]
    return {
        "path": _project_relative(slug, pdf),
        "file_sha": pdfpages.content_sha256(pdf),
        "page_count": ranked.get("page_count") or 0,
        # Stated, so "no page in this file carries a schedule marker" is a fact a
        # run can read rather than a conclusion it has to reach from an empty
        # search. A ranked page is only a word count: an accessibility sheet
        # scored 44 on `door` alone and was not a schedule.
        "schedule_pages": schedule_pages,
        "has_schedule_markers": bool(schedule_pages),
        # Sheet-ID / text-poor candidates (e.g. A4.0 with title-block-only text).
        "door_schedule_candidate_pages": sorted(set(candidate_pages)),
        "needs_visual_read_pages": sorted(
            {p["source_page"] for p in pages if p.get("needs_visual_read")}
        ),
        "pages": pages,
    }


def _unchanged(slug: str, existing: dict[str, Any], files: list[Path]) -> bool:
    recorded = {
        row.get("path"): row.get("file_sha")
        for row in (existing.get("files") or [])
        if isinstance(row, dict)
    }
    if len(recorded) != len(files):
        return False
    for pdf in files:
        if recorded.get(_project_relative(slug, pdf)) != pdfpages.content_sha256(pdf):
            return False
    return True


def total_page_count(slug: str) -> int:
    """Sum of PDF pages under uploads/raw/ (circuit-breaker input)."""
    raw = storage_root() / slug / "uploads" / "raw"
    if not raw.is_dir():
        return 0
    total = 0
    for pdf in sorted(raw.glob("*.pdf")):
        try:
            total += int(pdfpages.page_count(pdf))
        except Exception:
            continue
    return total


def exceeds_page_cap(slug: str, max_pages: int) -> tuple[bool, int]:
    """True when cumulative raw PDF pages exceed the extract circuit breaker.

    Used for the initial extract and every stragglerMerge follow-up — both sum
    the full uploads/raw tree, not just the delta pages.
    """
    if max_pages <= 0:
        return False, total_page_count(slug)
    pages = total_page_count(slug)
    return pages > max_pages, pages


def build_sheetmap(slug: str, *, force: bool = False) -> dict[str, Any]:
    """Write `extracted/_sheetmap.json` for every PDF under uploads/raw/.

    Skip the rewrite when every file SHA already matches, unless `force`.
    Does not write `line_items.json`.
    """
    project = storage_root() / slug
    raw = project / "uploads" / "raw"
    target = sheetmap_path(slug)
    files = sorted(raw.glob("*.pdf")) if raw.is_dir() else []

    if target.is_file() and not force:
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
        if isinstance(existing, dict) and _unchanged(slug, existing, files):
            # Re-applied on the skip path too: triage may have landed after the
            # last build, and it must not wait for a SHA to move to take effect.
            return _apply_triage(slug, existing)

    payload = {
        "generated_at": _now(),
        "files": [_file_entry(slug, pdf) for pdf in files],
    }
    payload = _apply_triage(slug, payload)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(target, payload)
    return payload
