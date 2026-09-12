"""The one LLM call per catalog: learn how this vendor lays a page out.

Every Hager page carries its section title on the fourth line of a running
header. ASI leads with column names, Rockwood and NGP with boilerplate, Pemko
varies. A fixed heuristic fits one vendor; a profile learned per catalog fits all
of them, and costs one call rather than one per page.

The model never sees a whole catalog and never reports a price. It looks at a
handful of sampled pages and answers two questions: where does the title live,
and what is this book. Everything else is string work in `describe`.

If no model is reachable the build still runs - `describe` falls back to the
page's own first line, and the overview says plainly that nobody summarised it.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import fitz

from cbc.core.llm import LLMClient
from cbc.pageindex.describe import describe_page, page_lines
from cbc.pageindex.models import CatalogOverview, PageEntry, PageProfile

log = logging.getLogger("cbc.pageindex.profile")

_PROFILE_SYSTEM = """You are indexing a vendor price book so an estimator's assistant can jump
straight to the right page instead of scanning hundreds.

You will see the first lines of several pages sampled across one catalog. Work
out how this publisher lays out a page, and answer ONLY with JSON:

{
  "title_source": "line_index:N" or "regex:^(pattern)$" or null,
  "printed_page_source": "line_index:N" or "regex:..." or null,
  "boilerplate": ["strings that repeat on every page and carry no meaning"],
  "code_pattern": "regex matching a part number here, or null",
  "notes": "one sentence on anything unusual",
  "overview": {
    "summary": "two sentences: what this catalog is and what it covers",
    "product_lines": ["the product families in it"],
    "how_prices_are_shown": "one sentence",
    "gotchas": "anything that would mislead a reader, e.g. page numbers restarting per section",
    "how_to_find_a_part": "one sentence on the fastest route to a part"
  }
}

`line_index` counts non-empty lines from 0. Choose it only when the same index
holds the title on EVERY sample. If the pages disagree, use a regex or null -
a wrong rule is applied to every page in the book, so null is better than a
guess. Never invent a price."""

_SECOND_LOOK_SYSTEM = """These pages of a vendor catalog could not be read by the layout rule that
worked for the rest of the book. For each, say what the page is.

Answer ONLY with JSON: {"pages": [{"pdf_page": N, "title": "...",
"description": "one or two sentences on what is on this page", "kind":
"price_table|item_numbers|prose|diagram|toc|unknown"}]}

If a page has no readable text, say so and use kind "diagram". Never invent a
price or a part number."""


def _sample_block(samples: list[tuple[int, str]], lines_per_page: int = 12) -> str:
    """The first lines of each sampled page, labelled and numbered."""
    blocks = []
    for page_number, text in samples:
        lines = page_lines(text)[:lines_per_page]
        numbered = "\n".join(f"  [{i}] {line[:110]}" for i, line in enumerate(lines))
        blocks.append(f"--- pdf page {page_number} ---\n{numbered or '  (no text layer)'}")
    return "\n\n".join(blocks)


def discover(
    file_name: str,
    vendor: str,
    samples: list[tuple[int, str]],
    *,
    client: LLMClient | None = None,
) -> tuple[PageProfile | None, CatalogOverview | None]:
    """Learn one catalog's page layout. One call. Never raises."""
    try:
        client = client or LLMClient.from_env()
        response = client.complete_json(
            system=_PROFILE_SYSTEM,
            user=f"Catalog: {file_name} (vendor: {vendor})\n\n{_sample_block(samples)}",
            document_id=file_name,
            prompt_version="pageindex-profile-1",
        )
        data = response.data or {}
    except Exception as exc:
        # A catalog still indexes without a model - worse descriptions, same
        # navigation. Failing the build here would make the index depend on a
        # provider being up, which is not a trade worth making.
        log.warning("%s: profile discovery unavailable (%s); using page text alone", file_name, exc)
        return None, None

    overview_raw = data.get("overview") or {}
    profile = PageProfile(
        title_source=_clean(data.get("title_source")),
        printed_page_source=_clean(data.get("printed_page_source")),
        boilerplate=[str(b) for b in (data.get("boilerplate") or []) if str(b).strip()][:12],
        code_pattern=_clean(data.get("code_pattern")),
        notes=str(data.get("notes") or "")[:300],
    )
    overview = CatalogOverview(
        summary=str(overview_raw.get("summary") or "")[:800],
        product_lines=[str(p) for p in (overview_raw.get("product_lines") or [])][:20],
        how_prices_are_shown=str(overview_raw.get("how_prices_are_shown") or "")[:400],
        gotchas=str(overview_raw.get("gotchas") or "")[:400],
        how_to_find_a_part=str(overview_raw.get("how_to_find_a_part") or "")[:400],
    )
    log.info("%s: profile title_source=%r", file_name, profile.title_source)
    return profile, overview


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def second_look(
    file_name: str,
    vendor: str,
    weak: list[PageEntry],
    doc: fitz.Document,
    *,
    batch_size: int = 20,
    client: LLMClient | None = None,
) -> list[PageEntry]:
    """Describe the few pages the profile could not resolve, in batches.

    Two percent of pages across the catalogs on file. Batched so the cost stays
    a handful of calls per catalog rather than one per straggler.
    """
    if not weak:
        return []
    try:
        client = client or LLMClient.from_env()
    except Exception as exc:
        log.warning("%s: no model for the second look (%s)", file_name, exc)
        return weak

    improved: list[PageEntry] = []
    for start in range(0, len(weak), batch_size):
        batch = weak[start : start + batch_size]
        samples = [(entry.pdf_page, doc[entry.pdf_page - 1].get_text()) for entry in batch]
        try:
            response = client.complete_json(
                system=_SECOND_LOOK_SYSTEM,
                user=f"Catalog: {file_name} (vendor: {vendor})\n\n{_sample_block(samples, 20)}",
                document_id=file_name,
                prompt_version="pageindex-secondlook-1",
            )
            answers = {int(p["pdf_page"]): p for p in (response.data or {}).get("pages", [])}
        except Exception as exc:
            log.warning("%s: second look failed for a batch (%s)", file_name, exc)
            improved.extend(batch)
            continue

        for entry in batch:
            answer = answers.get(entry.pdf_page)
            if not answer:
                improved.append(entry)
                continue
            improved.append(
                entry.model_copy(
                    update={
                        "title": str(answer.get("title") or entry.title)[:120],
                        "description": str(answer.get("description") or entry.description)[:400],
                        "kind": answer.get("kind") if answer.get("kind") in
                        {"price_table", "item_numbers", "prose", "diagram", "toc", "unknown"}
                        else entry.kind,
                        # Read by a model rather than resolved by the profile. Better
                        # than nothing and worth saying it is not the same evidence.
                        "confidence": 0.6,
                    }
                )
            )
    return improved


def _demo() -> None:
    """The sample block is what the model sees; it must carry line indices."""
    block = _sample_block([(297, "23\n03/01/2026\nwww.hagerco.com\nLocks - 3400 Series\n")])
    assert "[3] Locks - 3400 Series" in block, block
    assert "pdf page 297" in block

    empty = _sample_block([(5, "")])
    assert "(no text layer)" in empty

    # With no model reachable, discovery declines rather than inventing a rule.
    profile, overview = discover("x.pdf", "acme", [(1, "text")], client=_Broken())
    assert profile is None and overview is None

    # And the pages still describe, from their own text.
    entry = describe_page("Hinges\nBB1279  $9.00", 1, PageProfile())
    assert entry.title and entry.has_prices
    print("cbc.pageindex.profile OK")


class _Broken:
    def complete_json(self, **_: Any) -> Any:
        raise RuntimeError("no provider")


if __name__ == "__main__":
    _demo()
