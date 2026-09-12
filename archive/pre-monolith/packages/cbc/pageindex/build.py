"""Build one catalog's page index.

    python -m cbc.pageindex.build --all
    python -m cbc.pageindex.build hager_price_book_18.pdf
    python -m cbc.pageindex.build --all --force     # ignore the hash, re-read

Three passes, in cost order:

  1. profile discovery - one LLM call over a handful of sampled pages, learning
     where this vendor puts its section title and page number
  2. describe every page from that profile - no LLM, no network
  3. a second look at the pages the profile could not resolve

Measured across the fourteen catalogs on file: 1,216 pages, all of them titled,
and 27 - two percent - reaching pass 3. A call per page would have been three to
seven hours on a local model; this is minutes.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import fitz

from cbc.core.paths import repo_root
from cbc.pageindex import basis, store
from cbc.pageindex.describe import describe_page, needs_a_second_look
from cbc.pageindex.models import BUILDER_VERSION, PageIndexDocument, PageProfile

log = logging.getLogger("cbc.pageindex.build")

# Pages sampled for profile discovery. Spread rather than the first few, because
# a catalog's front matter looks nothing like its price tables.
SAMPLE_COUNT = 6


def _sample_pages(doc: fitz.Document) -> list[tuple[int, str]]:
    total = doc.page_count
    if total <= SAMPLE_COUNT:
        picks = range(1, total + 1)
    else:
        step = total // (SAMPLE_COUNT + 1)
        picks = [max(1, min(total, step * i)) for i in range(1, SAMPLE_COUNT + 1)]
    return [(n, doc[n - 1].get_text()) for n in picks]


def _inventory() -> dict[str, dict]:
    """The curated price-book inventory: vendor, kind and effective date."""
    path = repo_root() / "pricebooks" / "index.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {entry["file"]: entry for entry in payload.get("pricebooks", []) if entry.get("file")}


def describe_file(
    path: Path,
    *,
    vendor: str | None = None,
    kind: str | None = None,
    effective_date: str | None = None,
    use_llm: bool = True,
) -> PageIndexDocument | None:
    """Read and describe one catalog. Pure CPU and I/O on the file - no database.

    Kept separate from the write so the caller can run it on a thread: a 744-page
    book would otherwise stall the worker's heartbeat and its cancel watcher, and
    a motor client belongs to the loop that made it, so the save cannot go to the
    thread with it.
    """
    if not path.exists():
        raise FileNotFoundError(path)

    entry = _inventory().get(path.name, {})
    vendor = (vendor or entry.get("vendor") or "unknown").strip().lower()
    kind = kind or entry.get("kind") or "price_book"
    effective_date = effective_date or entry.get("effective_date")

    catalog_id = store.catalog_id_for(path.name)
    digest = store.file_hash(path)

    if path.suffix.lower() != ".pdf":
        # Spreadsheets have no pages. Deliberately not guessed at here - the
        # sheet/row locator is a separate shape and is built after the PDF path
        # is proven, rather than half-done now.
        log.warning("%s is not a PDF - spreadsheet indexing is not built yet", path.name)
        return None

    doc = fitz.open(str(path))
    try:
        samples = _sample_pages(doc)
        profile, overview = (None, None)
        if use_llm:
            from cbc.pageindex.profile import discover

            profile, overview = discover(path.name, vendor, samples)
        if profile is None:
            profile = PageProfile()

        pages = [
            describe_page(doc[i].get_text(), i + 1, profile) for i in range(doc.page_count)
        ]

        weak = [p for p in pages if needs_a_second_look(p)]
        if weak and use_llm:
            from cbc.pageindex.profile import second_look

            improved = second_look(path.name, vendor, weak, doc)
            by_page = {p.pdf_page: p for p in improved}
            pages = [by_page.get(p.pdf_page, p) for p in pages]

        document = PageIndexDocument(
            catalog_id=catalog_id,
            vendor=vendor,
            file_name=path.name,
            file_hash=digest,
            kind=kind,
            price_basis=basis.price_basis(path.name, vendor),
            effective_date=effective_date,
            page_count=doc.page_count,
            overview=overview or _fallback_overview(path.name, pages),
            profile=profile,
            pages=pages,
            built_at=datetime.now(timezone.utc).isoformat(),
            builder_version=BUILDER_VERSION,
            status="ready",
        )
    finally:
        doc.close()

    log.info(
        "%s described: %d pages, %d needed a second look",
        path.name, len(document.pages), len(weak),
    )
    return document


async def build_one(
    path: Path,
    *,
    vendor: str | None = None,
    kind: str | None = None,
    effective_date: str | None = None,
    force: bool = False,
    use_llm: bool = True,
) -> PageIndexDocument | None:
    """Index one catalog file. Returns None when it was already current."""
    if not path.exists():
        raise FileNotFoundError(path)

    catalog_id = store.catalog_id_for(path.name)
    current_hash = await asyncio.to_thread(store.file_hash, path)
    if not force and await store.stored_hash(catalog_id) == current_hash:
        log.info("%s unchanged - not re-read", path.name)
        return None

    document = await asyncio.to_thread(
        describe_file,
        path,
        vendor=vendor,
        kind=kind,
        effective_date=effective_date,
        use_llm=use_llm,
    )
    if document is not None:
        await store.save(document)
    return document


def _fallback_overview(file_name: str, pages: list) -> "object":
    """What the overview says when no model was available to write one.

    Counted from the pages themselves rather than left blank, so the catalog is
    still navigable without an LLM - and honest that nobody summarised it.
    """
    from cbc.pageindex.models import CatalogOverview

    priced = sum(1 for p in pages if p.has_prices)
    families: dict[str, int] = {}
    for page in pages:
        for code in page.code_prefixes[:3]:
            families[code] = families.get(code, 0) + 1
    top = [c for c, _ in sorted(families.items(), key=lambda kv: -kv[1])[:12]]
    return CatalogOverview(
        summary=(
            f"{file_name}: {len(pages)} pages, {priced} carrying prices. "
            "No model was available to summarise this catalog; the page index "
            "below was built from the pages themselves."
        ),
        product_lines=top,
        how_prices_are_shown="Not summarised - open a page to see.",
        how_to_find_a_part="Search the page descriptions with find_pages.",
    )


async def build_all(*, force: bool = False, use_llm: bool = True) -> int:
    directory = repo_root() / "pricebooks"
    built = 0
    for path in sorted(directory.glob("*.pdf")):
        try:
            if await build_one(path, force=force, use_llm=use_llm):
                built += 1
        except Exception as exc:  # one bad catalog must not stop the rest
            log.exception("%s failed to index: %s", path.name, exc)
    return built


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", nargs="?", help="a file in pricebooks/, or --all")
    parser.add_argument("--all", action="store_true", help="every PDF in pricebooks/")
    parser.add_argument("--force", action="store_true", help="rebuild even if unchanged")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="skip profile discovery; describe from the page text alone",
    )
    args = parser.parse_args()

    use_llm = not args.no_llm
    if args.all:
        count = asyncio.run(build_all(force=args.force, use_llm=use_llm))
        print(f"{count} catalog(s) indexed")
        return 0
    if not args.file:
        parser.error("give a file name or --all")

    path = repo_root() / "pricebooks" / args.file
    document = asyncio.run(build_one(path, force=args.force, use_llm=use_llm))
    if document is None:
        print(f"{args.file} was already current")
        return 0
    print(f"{document.file_name}: {document.page_count} pages indexed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
