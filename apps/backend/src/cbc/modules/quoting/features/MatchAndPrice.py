"""The match_and_price job: a Claude pass matches the openings to catalog parts and prices them.

The pass reads the catalog through its MCP server, so it is refused when there is
no read-only credential to hand that server. What it priced is synced into
`estimateLines`, the quote is rolled up, and the matching gate runs over the bid.
It lives in quoting rather than pricing: it writes quoting's lines and quote, and
pricing may not import quoting.
"""
from __future__ import annotations

from typing import Any

from cbc.modules.extraction.api import passes
from cbc.modules.projects.api import bids, pipeline
from cbc.modules.quoting.api import priced_lines, quote
from cbc.services import matching_gate  # ponytail: legacy kernel; the gate moves here when services/ is sliced


async def run(job: dict[str, Any]) -> None:
    await pipeline.run_pass(job, sync=sync_results, needs_catalog=True)


async def sync_results(job: dict[str, Any], project: dict[str, Any] | None) -> str:
    note = await passes.check_output(job, project)
    if note is not None:
        return note
    counts = await priced_lines.import_quote_lines(project, job=job)
    if counts.get("aborted"):
        return "lease stolen; discarded output"
    await quote.persist(project)
    await matching_gate.apply_to_project(project)
    await bids.set_stage(project["_id"], "quote", 67)
    return f"{counts['inserted']} priced, {counts['updated']} updated, {counts['skipped']} kept"
