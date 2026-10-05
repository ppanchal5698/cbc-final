"""The bid digest: the whole bid set, page by page, as markdown a phase reads first.

Built from documentPages once a bid's documents are parsed, so every later phase
starts from what is actually on the sheets instead of searching for it - and
cannot invent what is not there. Written to

    extracted/digest/index.md           one line per page: file, page, sheet, trust
    extracted/digest/<document>.md      every block of every page, in reading order

Each block carries its page and box (`<!-- p12 b7 [x0,y0,x1,y1] -->`), so a value
taken from the digest still cites a rectangle on a sheet (NFR-3). A block whose
words the PDF's own text layer does not have at that spot is marked
`UNVERIFIED`; one read off an image with no text layer to check is marked
`FROM IMAGE`. Neither is a fact until an estimator or the sheet confirms it.
"""
from __future__ import annotations

import re
from typing import Any

from cbc.modules.intake.infrastructure.collections import document_pages, documents
from cbc.shared import storage
from cbc.shared.storage import atomic_write_text

AGREES = 0.6  # below this share of a block's words found on the sheet, it is unverified
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _mark(block: dict[str, Any]) -> str:
    agrees = block.get("agrees")
    if agrees is None:
        return "FROM IMAGE " if block.get("text") else ""
    return "" if agrees >= AGREES else f"UNVERIFIED ({agrees:.0%} on sheet) "


def _heading(blocks: list[dict[str, Any]]) -> str:
    for block in blocks:
        if block.get("type") in ("title", "section-header") and (block.get("text") or "").strip():
            return " ".join(block["text"].strip("# ").split())[:80]
    return ""


def render_document(doc: dict[str, Any], pages: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """(markdown for one document, its index lines)."""
    name = doc.get("filename") or str(doc["_id"])
    out = [f"# {name}", "", f"{len(pages)} page(s). Blocks in reading order; "
           "`UNVERIFIED` / `FROM IMAGE` blocks are not facts until checked against the sheet.", ""]
    index: list[str] = []
    for page in pages:
        blocks = [b for b in page.get("blocks") or [] if (b.get("text") or "").strip()]
        parser = (page.get("parser") or {}).get("name") or "?"
        doubtful = sum(1 for b in blocks if _mark(b))
        heading = _heading(blocks)
        out += [f"## Page {page['page']}" + (f" — {heading}" if heading else ""), "",
                f"_read by {parser}; {len(blocks)} block(s), {doubtful} unverified_", ""]
        for block in blocks:
            box = [round(float(v), 1) for v in block.get("bbox") or []]
            out.append(f"<!-- p{page['page']} b{block.get('n')} {box} -->")
            text = block["text"].strip()
            mark = _mark(block)
            out.append(f"**{mark.strip()}** {text}" if mark else text)
            out.append("")
        index.append(f"| {name} | {page['page']} | {heading or '-'} | {parser} | {len(blocks)} | {doubtful} |")
    return "\n".join(out), index


async def build(project: dict[str, Any]) -> dict[str, Any]:
    """Rewrite the bid's digest from its parsed pages. Never raises for content."""
    root = storage.project_dir(project["slug"]) / "extracted" / "digest"
    root.mkdir(parents=True, exist_ok=True)
    index = ["# Bid digest", "",
             "Read this before opening a PDF. Every block cites `<!-- p<page> b<block> [box] -->`.", "",
             "| File | Page | Sheet | Read by | Blocks | Unverified |", "|---|---|---|---|---|---|"]
    written = 0
    async for doc in documents().find({"projectId": project["_id"]}).sort("filename", 1):
        pages = await document_pages().find(
            {"documentId": doc["_id"], "contentSha": doc.get("contentSha")}
        ).sort("page", 1).to_list(None)
        if not pages:
            continue
        markdown, lines = render_document(doc, pages)
        stem = _SAFE.sub("_", (doc.get("filename") or str(doc["_id"])).rsplit(".", 1)[0])[:80]
        atomic_write_text(root / f"{stem}.md", markdown)
        index += lines
        written += 1
    atomic_write_text(root / "index.md", "\n".join(index) + "\n")
    return {"documents": written, "path": str(root / "index.md")}
