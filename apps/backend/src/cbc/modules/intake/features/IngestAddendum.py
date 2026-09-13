"""The ingest_addendum job: a Claude pass reads an addendum against the bid set it changes.

The pass gets a sheet map first; what it found - openings added, removed and
changed - is synced as the addendum's diff.
"""
from __future__ import annotations

from typing import Any

from cbc.modules.extraction.api import passes
from cbc.modules.projects.api import pipeline
from cbc.services import sync  # ponytail: legacy kernel; import_addendum moves here when services/sync_phases is sliced


async def run(job: dict[str, Any]) -> None:
    await pipeline.run_pass(job, sync=sync_results, prepare=passes.prepare)


async def sync_results(job: dict[str, Any], project: dict[str, Any] | None) -> str:
    note = await passes.check_output(job, project)
    if note is not None:
        return note
    counts = await sync.import_addendum(project, job)
    return (
        f"{counts['added']} added, {counts['removed']} removed, "
        f"{counts['changed']} changed in addendum diff"
    )
