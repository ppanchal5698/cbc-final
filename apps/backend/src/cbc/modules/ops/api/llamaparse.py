"""LlamaParse Cloud client: one window of pages in, parser-neutral blocks out.

Replaces the MinerU HTTP client. The shape returned here is what `normalise_window`
consumes, so nothing downstream - documentPages, the MCP servers, the sheet viewer,
the validators - has to know which parser produced it.

Everything in this module was measured against the live API on 2026-09-23, against
page 19 of the Baldwin set (a 270-rotated CAD sheet, page.rect 2448x1584). The
docs describe a flow that does not match the live service in two places, so the
notes below are the record:

* `POST /api/v2/parse/upload` uploads *and* parses in one call and returns a JOB,
  not a file. Using it per window would re-send the whole 20 MB document every
  time. `POST /api/v1/files` (multipart field `upload_file`) returns a real
  file_id that `POST /api/v2/parse` accepts, so a document is uploaded once and
  every window reuses it.
* `page_ranges.target_pages` is a comma-separated, **1-based** page list, and the
  sidecar reports `page_number` **1-based and absolute**: ask for "18,19,20" and
  you get back 18, 19, 20, meaning those sheets. So page numbers pass straight
  through - no offset in either direction.

  The v1 endpoint (`/api/v1/parsing/upload`) is 0-based, which is a genuine trap:
  a spike against v1 says subtract one, and carrying that into v2 sends page 0.
  The API rejects that outright ("Page numbers must be positive (1-based)"),
  which is lucky - the matching `page_number + 1` on the way back would have
  filed every block one sheet off, and nothing downstream could have noticed.

Two things are deliberately NOT trusted:

* **Item-level `bBox` is discarded.** It is the region the parser considered, not
  the content's bounds. Measured: the door-schedule table claimed 2336x1525 of a
  2448x1584 sheet, and the heading "snpdesign ARCHITECTS" claimed 806x1322 at
  confidence 0.4. A box that size is not evidence - an estimator clicking it is
  shown a third of the drawing. Block boxes here are the union of the item's
  grounding lines, which are tight and real.
* **Granular grounding is required, not optional.** A result with no grounded
  items is treated as a failed parse rather than stored as a page with no
  coordinates, for the same reason the MinerU client refused a status stub: a
  page recorded without boxes looks parsed forever and silently yields values
  nothing can point at.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Iterable

import httpx

log = logging.getLogger(__name__)

API_ROOT = "https://api.cloud.llamaindex.ai"
FILES_URL = f"{API_ROOT}/api/v1/files"
PARSE_URL = f"{API_ROOT}/api/v2/parse"

POLL_SECONDS = 3.0

# `fast` is excluded on purpose: it returns no granular bboxes, and without those
# a priced line has no rectangle on the sheet to point at (NFR-3).
TIERS = ("cost_effective", "agentic", "agentic_plus")
DEFAULT_TIER = "cost_effective"

GRANULARITY = ["word", "line", "cell"]

_TERMINAL_OK = {"COMPLETED", "SUCCESS", "PARTIAL_SUCCESS"}
_TERMINAL_BAD = {"FAILED", "ERROR", "CANCELLED"}

# A bad key or a malformed request will not come good on a retry; anything else
# might, so it goes back on the queue.
_PERMANENT_STATUS = {400, 401, 403, 404, 422}

# LlamaParse item types -> the vocabulary already stored in documentPages.
# Keeping the existing words matters: `verify_page` excludes discarded/image/
# figure, bid-docs surfaces `type` to agents, and the viewer colours by it.
_TYPE_MAP = {
    "text": "text",
    "paragraph": "text",
    "heading": "title",
    "title": "title",
    "table": "table",
    "image": "image",
    "figure": "image",
    "code": "code",
    "list": "list",
    # Sheet numbers and title-block furniture live here. They must be present
    # (sheetmap reads them) but must not be scored by verify_page.
    "header": "discarded",
    "footer": "discarded",
    "page_number": "discarded",
}


class ParseRetryable(RuntimeError):
    """Transient: the window goes back on the queue."""


class ParsePermanent(RuntimeError):
    """Will not come good on a retry."""


def _raise_for_status(response: httpx.Response, what: str) -> None:
    if response.status_code < 400:
        return
    detail = response.text[:300]
    message = f"{what} failed ({response.status_code}): {detail}"
    if response.status_code in _PERMANENT_STATUS:
        raise ParsePermanent(message)
    raise ParseRetryable(message)


def _box(raw: Any) -> list[float] | None:
    """LlamaParse {x,y,w,h} -> the [x0,y0,x1,y1] every consumer already expects."""
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if not isinstance(raw, dict):
        return None
    try:
        x, y = float(raw["x"]), float(raw["y"])
        w, h = float(raw["w"]), float(raw["h"])
    except (KeyError, TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return [round(x, 2), round(y, 2), round(x + w, 2), round(y + h, 2)]


def _union(boxes: Iterable[list[float]]) -> list[float] | None:
    kept = [b for b in boxes if b]
    if not kept:
        return None
    return [
        round(min(b[0] for b in kept), 2),
        round(min(b[1] for b in kept), 2),
        round(max(b[2] for b in kept), 2),
        round(max(b[3] for b in kept), 2),
    ]


def _slice(md: str, span: Any) -> str:
    """Grounding spans index into the item's markdown."""
    if not isinstance(span, (list, tuple)) or len(span) < 2:
        return ""
    try:
        return md[int(span[0]):int(span[1])]
    except (TypeError, ValueError):
        return ""


def _lines_from_grounding(grounding: dict, md: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in grounding.get("lines") or []:
        if not isinstance(line, dict):
            continue
        box = _box(line.get("bbox"))
        if box is None:
            continue
        out.append({"text": _slice(md, line.get("span")).strip(), "bbox": box})
    return out


def _cells_from_grounding(grounding: dict) -> list[list[float]]:
    """Per-cell rectangles for a table.

    This is the evidence an estimator actually clicks: not "somewhere on this
    sheet", but the cell the fire rating was read out of.
    """
    cells: list[list[float]] = []
    for row in grounding.get("rows") or []:
        if not isinstance(row, list):
            continue
        for cell in row:
            if not isinstance(cell, dict):
                continue
            box = _box(cell.get("bbox"))
            if box is not None:
                cells.append(box)
    return cells


# A run breaks when the vertical gap exceeds this multiple of the line height.
# Normal paragraph leading is well under 1x; 2x keeps a paragraph together and
# still splits a heading whose next "line" is 1300pt down the sheet.
_LEADING_TOLERANCE = 2.0


def _clusters(lines: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Split an item's lines into spatially contiguous runs.

    LlamaParse groups items by reading order and semantic role, not position.
    Measured on the real door-schedule sheet: one `heading` item carried lines at
    y = 222, 250, 285 and 1526, and one `text` item spanned 1316 points. Unioning
    those gives a box covering a quarter to half the drawing - which is exactly
    as useless as the item's own bBox, and it is what dragged verify_page to 0.48.

    Clustering costs one sort per item and turns each of those into several tight
    boxes an estimator can actually click.
    """
    usable = [ln for ln in lines if ln.get("bbox")]
    if len(usable) <= 1:
        return [usable] if usable else []
    ordered = sorted(usable, key=lambda ln: (ln["bbox"][1], ln["bbox"][0]))
    runs: list[list[dict[str, Any]]] = [[ordered[0]]]
    for line in ordered[1:]:
        prev = runs[-1][-1]["bbox"]
        cur = line["bbox"]
        gap = cur[1] - prev[3]
        leading = max(prev[3] - prev[1], cur[3] - cur[1], 1.0)
        overlap = min(prev[2], cur[2]) - max(prev[0], cur[0])
        if gap <= leading * _LEADING_TOLERANCE and overlap > 0:
            runs[-1].append(line)
        else:
            runs.append([line])
    return runs


def _blocks(raw: dict) -> list[dict[str, Any]]:
    """One grounded item -> one block per spatially contiguous run of its lines."""
    grounding = raw.get("grounding")
    if not isinstance(grounding, dict):
        return []
    md = str(raw.get("md") or "")
    kind = _TYPE_MAP.get(str(raw.get("type") or "").lower(), "text")

    if kind == "table":
        # A table is one spatially coherent region; its cells are the evidence.
        cells = _cells_from_grounding(grounding)
        box = _union(cells) or _union(
            _box(b) for b in (grounding.get("row_bboxes") or [])
        )
        if box is None:
            return []
        block: dict[str, Any] = {"type": kind, "text": md.strip(), "bbox": box}
        if cells:
            block["cells"] = cells
        return [block]

    out: list[dict[str, Any]] = []
    for run in _clusters(_lines_from_grounding(grounding, md)):
        box = _union(ln["bbox"] for ln in run)
        if box is None:
            continue
        text = " ".join(ln["text"] for ln in run if ln["text"]).strip()
        block = {"type": kind, "text": text or md.strip(), "bbox": box}
        if run:
            block["lines"] = run
        out.append(block)
    return out


def _page(row: dict) -> dict[str, Any] | None:
    """One sidecar JSONL row -> one window page, 1-based and absolute."""
    if not row.get("success", True):
        return None
    number = row.get("page_number")
    if not isinstance(number, int):
        return None
    width, height = row.get("page_width"), row.get("page_height")
    if not width or not height:
        return None

    items: list[dict[str, Any]] = []
    for raw in row.get("items") or []:
        if isinstance(raw, dict):
            items.extend(_blocks(raw))
    return {
        "page": number,  # sidecar page_number is already 1-based and absolute
        "width": float(width),
        "height": float(height),
        "items": items,
    }


async def upload(client: httpx.AsyncClient, *, api_key: str, path: str | Path) -> str:
    """Upload once per document; every window then reuses the file_id."""
    source = Path(path)
    if not source.is_file():
        raise ParsePermanent(f"PDF not found: {source}")
    blob = source.read_bytes()
    response = await client.post(
        FILES_URL,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        files={"upload_file": (source.name, blob, "application/pdf")},
    )
    _raise_for_status(response, "file upload")
    file_id = (response.json() or {}).get("id")
    if not file_id:
        raise ParseRetryable("file upload returned no id")
    return str(file_id)


async def parse_window(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    file_id: str,
    start_page: int,
    end_page: int,
    tier: str = DEFAULT_TIER,
    timeout: float = 1800.0,
    cancelled: Callable[[], Any] | None = None,
) -> list[dict[str, Any]]:
    """Parse pages [start_page, end_page] (1-based, inclusive) of an uploaded file."""
    if tier not in TIERS:
        raise ParsePermanent(
            f"tier {tier!r} is not one of {TIERS}. `fast` returns no granular "
            "bboxes, so a parsed line would have no rectangle to point at"
        )
    if end_page < start_page:
        raise ParsePermanent(f"empty window {start_page}-{end_page}")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    wanted = list(range(start_page, end_page + 1))
    body = {
        "file_id": file_id,
        "tier": tier,
        "version": "latest",
        "output_options": {"granular_bboxes": GRANULARITY},
        # target_pages is 1-based on v2 (v1 is 0-based - see the module docstring).
        "page_ranges": {"target_pages": ",".join(str(p) for p in wanted)},
    }
    response = await client.post(PARSE_URL, headers=headers, json=body)
    _raise_for_status(response, "parse job")
    job_id = (response.json() or {}).get("id")
    if not job_id:
        raise ParseRetryable("parse job returned no id")

    status = await _await_job(client, api_key, job_id, timeout=timeout, cancelled=cancelled)
    if status in _TERMINAL_BAD:
        raise ParseRetryable(f"parse job {job_id} ended {status}")

    rows = await _grounded_rows(client, api_key, job_id)
    pages = [p for p in (_page(r) for r in rows) if p is not None]

    returned = {p["page"] for p in pages}
    unexpected = returned - set(wanted)
    if unexpected:
        # A page outside the window means the request and the answer disagree;
        # storing it would file blocks under the wrong sheet.
        raise ParsePermanent(
            f"parse job {job_id} returned pages {sorted(unexpected)} "
            f"outside the requested window {start_page}-{end_page}"
        )

    # A requested page the parser did not return is recorded empty rather than
    # dropped. The resume count stays honest and sheetmap routes it to a visual
    # read instead of the page quietly vanishing from the document.
    for number in wanted:
        if number not in returned:
            pages.append({"page": number, "width": 0.0, "height": 0.0, "items": []})
    pages.sort(key=lambda p: p["page"])
    return pages


async def _await_job(
    client: httpx.AsyncClient,
    api_key: str,
    job_id: str,
    *,
    timeout: float,
    cancelled: Callable[[], Any] | None,
) -> str:
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    deadline = time.monotonic() + timeout
    while True:
        if cancelled is not None:
            stop = cancelled()
            if asyncio.iscoroutine(stop):
                stop = await stop
            if stop:
                raise ParsePermanent("cancelled by estimator")
        response = await client.get(f"{PARSE_URL}/{job_id}", headers=headers)
        _raise_for_status(response, "parse status")
        body = response.json() or {}
        status = str((body.get("job") or body).get("status") or "").upper()
        if status in _TERMINAL_OK or status in _TERMINAL_BAD:
            return status
        if time.monotonic() >= deadline:
            raise ParseRetryable(f"parse job {job_id} still {status or 'pending'} after {timeout:.0f}s")
        await asyncio.sleep(POLL_SECONDS)


async def _grounded_rows(
    client: httpx.AsyncClient, api_key: str, job_id: str
) -> list[dict[str, Any]]:
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    response = await client.get(
        f"{PARSE_URL}/{job_id}?expand=items_content_metadata", headers=headers
    )
    _raise_for_status(response, "parse result")
    payload = response.json() or {}
    meta = payload.get("result_content_metadata") or {}
    grounded = meta.get("grounded_items") or {}
    url = grounded.get("presigned_url")
    if not url:
        # We asked for granular boxes and got none. Treated as a failed parse for
        # the same reason a MinerU status stub was: a page stored without
        # coordinates reads as parsed forever.
        raise ParseRetryable(f"parse job {job_id} returned no grounded items")

    # Presigned S3 URL - it carries its own auth, and sending ours would be
    # rejected as a conflicting credential.
    sidecar = await client.get(url)
    _raise_for_status(sidecar, "grounded items download")
    rows: list[dict[str, Any]] = []
    for line in sidecar.text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    if not rows:
        raise ParseRetryable(f"parse job {job_id} grounded sidecar was empty")
    return rows
