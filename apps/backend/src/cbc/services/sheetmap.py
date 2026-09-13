"""Deterministic sheet map written before a take-off prompt is built (B-11).

`find_sheets` is the same work on every extract job. The worker runs it once,
merges schedule-marker pages from `parse_schedule.find_schedule_pages`, and
writes `extracted/_sheetmap.json` so Claude reads the ranked pages instead of
searching the set again.

Pages carry `roles` (title / door_schedule / hardware / frp / finish) so each
subagent receives only the page lists it needs.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cbc.core import pdfpages
from cbc.shared.paths import repo_root
from cbc.services.storage import atomic_write_json

ROOT = repo_root()
PROJECTS = ROOT / "projects"
SHEETMAP_REL = "extracted/_sheetmap.json"
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
    "hardware": ("hardware", "hw set", "hardware set", "lockset"),
    "frp": ("frp", "fiberglass", "wall panel", "j-channel", "cove base"),
    "finish": ("finish schedule", "room finish", "finish"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sheetmap_path(slug: str) -> Path:
    return PROJECTS / slug / SHEETMAP_REL


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
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _find_sheets(file_path: str) -> dict[str, Any]:
    from _runtime import load_server

    return load_server("pdf-tools").find_sheets(file_path)


def _roles_for_page(terms: dict[str, Any] | None, markers: list[str]) -> list[str]:
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
    if upper_markers & {"DOOR SCHEDULE", "DOOR TYPE SCHEDULE", "FRAME SCHEDULE", "OPENING SCHEDULE"}:
        roles.add("door_schedule")
    if upper_markers & {"FINISH SCHEDULE", "ROOM FINISH SCHEDULE"}:
        roles.add("finish")
    if any("FRP" in m or "FIBERGLASS" in m or "WALL PANEL" in m for m in upper_markers):
        roles.add("frp")
    if any("TITLE" in m or "COVER" in m or "INDEX" in m for m in upper_markers):
        roles.add("title")
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
        roles = _roles_for_page(terms if isinstance(terms, dict) else {}, found)
        pages.append(
            {
                "source_page": source_page,
                "score": row.get("score") or 0,
                "terms": terms,
                "kind": "schedule" if found else "ranked",
                "why": ", ".join(found) if found else ", ".join(str(t) for t in terms),
                "markers": found,
                "roles": roles,
            }
        )
    for source_page, found in sorted(by_marker.items()):
        if source_page in seen:
            continue
        roles = _roles_for_page({}, found)
        pages.append(
            {
                "source_page": source_page,
                "score": 0,
                "terms": {},
                "kind": "schedule",
                "why": ", ".join(found),
                "markers": found,
                "roles": roles,
            }
        )
    # A page carrying a real schedule marker outranks any page that merely uses
    # the words a lot. Sorted on score alone, an accessibility details sheet with
    # 30 uses of "door" led the map on a bid whose Division 08 scope was nil.
    pages.sort(
        key=lambda p: (
            0 if p.get("kind") == "schedule" else 1,
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
            page_roles = {str(r).lower() for r in (page.get("roles") or [])}
            if wanted and not (page_roles & wanted):
                continue
            hits.append(
                {
                    "path": path,
                    "source_page": page.get("source_page"),
                    "roles": list(page.get("roles") or []),
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
    raw = PROJECTS / slug / "uploads" / "raw"
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
    Does not write `door_schedule.json`.
    """
    project = PROJECTS / slug
    raw = project / "uploads" / "raw"
    target = sheetmap_path(slug)
    files = sorted(raw.glob("*.pdf")) if raw.is_dir() else []

    if target.is_file() and not force:
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
        if isinstance(existing, dict) and _unchanged(slug, existing, files):
            return existing

    payload = {
        "generated_at": _now(),
        "files": [_file_entry(slug, pdf) for pdf in files],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(target, payload)
    return payload
