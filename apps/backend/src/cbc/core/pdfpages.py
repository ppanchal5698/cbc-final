"""Reading a page's geometry and rendering it to an image.

The estimator checks an extracted value against the real drawing, so the API
serves real page renders; the pdf-tools MCP server offers the same two operations
to a run. Both used to have their own copy - or worse, the API exec-ed the
server's module in-process through a custom loader to borrow them.

Bboxes are measured in PDF points against `page_size`, and the viewer scales them
itself, so these two have to agree exactly. Here they are the same code.
"""
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
from cbc.core.paths import repo_root

ROOT = repo_root()

# Rendered pages are derived data: cheap to recreate, and not something to leave
# beside the drawings they came from. Shared with api/services/pdf.py so there is
# one cache rather than two.
RENDER_CACHE = ROOT / ".cache" / "pdf-pages"
PRICEBOOKS = ROOT / "pricebooks"
REFERENCE_LIBRARY = ROOT / "reference-library"
RENDERER_VERSION = str(getattr(fitz, "version", "unknown"))

# Anthropic's documented long-edge cap for a useful vision token budget.
MAX_LONG_EDGE_PX = 1568
MAX_DPI = 300
MIN_DPI = 36


def _near_miss(path: Path) -> str:
    """A close-enough real path, when the one asked for does not exist.

    "PDF not found" is a dead end: a run that typed `dunkin_donots_remodel` for
    `dunkin_donuts_remodel` spent three searches on it, concluded the schedule
    was not there and moved on. One letter, and the error said nothing about it.
    """
    import difflib

    parent = path.parent
    if not parent.is_dir():
        # The directory is where a slug typo lands, so look one level up for it.
        grandparent = parent
        while grandparent != grandparent.parent and not grandparent.is_dir():
            grandparent = grandparent.parent
        if not grandparent.is_dir():
            return ""
        candidates = [entry.name for entry in grandparent.iterdir() if entry.is_dir()]
        missing = path.relative_to(grandparent).parts[0] if path != grandparent else ""
        close = difflib.get_close_matches(missing, candidates, n=1, cutoff=0.7)
        return f" Did you mean directory {close[0]!r} rather than {missing!r}?" if close else ""

    close = difflib.get_close_matches(
        path.name, [entry.name for entry in parent.iterdir()], n=1, cutoff=0.7
    )
    return f" Did you mean {close[0]!r}?" if close else ""


def _open(file_path: str | Path) -> fitz.Document:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {file_path}.{_near_miss(path)}")
    return fitz.open(path)


def page_count(file_path: str | Path) -> int:
    doc = _open(file_path)
    try:
        return doc.page_count
    finally:
        doc.close()


def page_size(file_path: str | Path, page_number: int) -> dict[str, Any]:
    """Page dimensions in PDF points - the frame every bbox is measured against."""
    doc = _open(file_path)
    try:
        index = page_number - 1
        if not 0 <= index < doc.page_count:
            raise ValueError(f"page {page_number} out of range (1-{doc.page_count})")
        rect = doc[index].rect
        return {
            "file": str(file_path),
            "source_page": page_number,
            "page_count": doc.page_count,
            "width": round(rect.width, 2),
            "height": round(rect.height, 2),
            "units": "PDF points",
        }
    finally:
        doc.close()


def _writable_target(file_path: Path, out_dir: str | Path | None) -> Path:
    """Where a rendered page may be written.

    Defaulting to the source PDF's own directory was wrong in two ways that only
    show up in a real run. Rendering a page of a bid set dropped
    `1_Architectural_p12_200dpi.png` into `projects/{slug}/uploads/raw/`, where
    `.claude/rules/file-safety.md` says the uploads are immutable and extraction
    output belongs in `uploads/processed/` or `extracted/`. Rendering a page of a
    price book would try to write into `pricebooks/`, which is read-only during a
    run and mounted `:ro` on the worker.

    Neither was caught by the PreToolUse guard, because this write happens inside
    PyMuPDF rather than through Write or Bash - so the check lives here, next to
    the write it governs.
    """
    root = ROOT.resolve()
    target = Path(out_dir).resolve() if out_dir else RENDER_CACHE.resolve()
    allowed_roots = (
        RENDER_CACHE.resolve(),
        (root / "projects").resolve(),
        (root / ".cache").resolve(),
    )
    if not any(target == allowed or allowed in target.parents for allowed in allowed_roots):
        raise ValueError(
            f"refusing to write a rendered page outside allowed directories: {target}"
        )
    for protected in (PRICEBOOKS, REFERENCE_LIBRARY):
        if target == protected or protected in target.parents:
            raise ValueError(
                f"refusing to write a rendered page into {protected.name}/ - it is "
                "read-only reference data (.claude/rules/file-safety.md)"
            )
    if target.name == "raw" and target.parent.name == "uploads":
        raise ValueError(
            "refusing to write a rendered page into uploads/raw/ - raw uploads are "
            "immutable; use uploads/processed/ or leave out_dir unset"
        )
    return target


@lru_cache(maxsize=64)
def _file_sha256(resolved: str, size: int, mtime_ns: int) -> str:
    """Content hash, keyed so a 15 MB drawing is not re-read on every page."""
    digest = hashlib.sha256()
    with open(resolved, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def content_sha256(file_path: str | Path) -> str:
    """Content SHA-256 of a PDF, memoised on (path, size, mtime)."""
    path = Path(file_path).resolve()
    stat = path.stat()
    return _file_sha256(str(path), stat.st_size, stat.st_mtime_ns)


def _region_key(region: list[float] | None) -> str:
    if not region:
        return "none"
    return ",".join(f"{float(value):.4f}" for value in region[:4])


def render_cache_name(
    file_path: Path,
    page_number: int,
    dpi: int,
    region: list[float] | None = None,
) -> str:
    """On-disk name: content SHA-256 of the PDF, plus page, dpi, region, renderer."""
    path = file_path.resolve()
    stat = path.stat()
    content_sha = _file_sha256(str(path), stat.st_size, stat.st_mtime_ns)
    digest = hashlib.sha256(
        f"{content_sha}|{page_number}|{dpi}|{_region_key(region)}|{RENDERER_VERSION}".encode()
    ).hexdigest()[:24]
    return f"{digest}.png"


def _clamp_dpi(requested: int, page: fitz.Page, region: list[float] | None) -> int:
    dpi = max(MIN_DPI, min(int(requested), MAX_DPI))
    if region:
        return dpi
    long_pt = max(page.rect.width, page.rect.height)
    if long_pt <= 0:
        return dpi
    max_for_edge = int(MAX_LONG_EDGE_PX * 72 / long_pt)
    if max_for_edge < dpi:
        dpi = max(MIN_DPI, max_for_edge)
    return dpi


def page_image(
    file_path: str | Path,
    page_number: int,
    dpi: int = 200,
    out_dir: str | Path | None = None,
    region: list[float] | None = None,
) -> dict[str, Any]:
    """Render one page (or a clip) to PNG. Full-page long edge is ≤1568 px."""
    path = Path(file_path)
    target = _writable_target(path, out_dir)
    target.mkdir(parents=True, exist_ok=True)
    doc = _open(path)
    try:
        index = page_number - 1
        if not 0 <= index < doc.page_count:
            raise ValueError(f"page {page_number} out of range (1-{doc.page_count})")
        page = doc[index]
        effective_dpi = _clamp_dpi(dpi, page, region)
        output = target / render_cache_name(path, page_number, effective_dpi, region)
        hit = {
            "source_page": page_number,
            "image_path": str(output),
            "dpi": effective_dpi,
            "file": str(file_path),
        }
        if output.exists():
            return hit
        if region:
            clip = fitz.Rect(region[0], region[1], region[2], region[3])
            page.get_pixmap(clip=clip, dpi=effective_dpi).save(output)
        else:
            page.get_pixmap(dpi=effective_dpi).save(output)
        return hit
    finally:
        doc.close()


def find_text(file_path: str | Path, page_number: int, needle: str) -> list[dict[str, Any]]:
    """Locate a string on a page and return its bboxes.

    Fallback for a line whose stored bbox is missing - an older extraction, or a
    value the estimator typed by hand and wants to point at.
    """
    doc = _open(file_path)
    try:
        index = page_number - 1
        if not 0 <= index < doc.page_count:
            return []
        page = doc[index]
        return [
            {
                "bbox": [round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2)],
                "pageSize": {
                    "width": round(page.rect.width, 2),
                    "height": round(page.rect.height, 2),
                },
            }
            for r in page.search_for(needle)[:20]
        ]
    finally:
        doc.close()
