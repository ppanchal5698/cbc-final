"""The build_proposal job: a Claude pass writes the draft quotation and review pack.

The quotation and review summary are then rendered by the scripts, whatever the
pass wrote, and the artifacts recorded on the proposal. QUOTE_COMPLETED then ends the bid's saga at
`complete`, in projects - a draft for the estimator, never a sent quote (NFR-1).
"""
from __future__ import annotations

import asyncio
from typing import Any

from cbc.modules.extraction.api import passes
from cbc.modules.ops.api import jobs as ops_jobs
from cbc.modules.projects.api import pipeline
from cbc.modules.quoting.api import proposal_artifacts
from cbc.shared import events


async def run(job: dict[str, Any]) -> None:
    await pipeline.run_pass(job, sync=sync_results)


async def sync_results(job: dict[str, Any], project: dict[str, Any] | None) -> str:
    note = await passes.check_output(job, project)
    if note is not None:
        return note
    if not await ops_jobs.holds_lease(job):
        return "lease stolen; discarded output"
    failed = await asyncio.to_thread(proposal_artifacts.render_artifacts, job["type"], project["slug"])
    artifacts = await proposal_artifacts.import_proposal_artifacts(project)
    await events.publish(events.QUOTE_COMPLETED, project_id=project["_id"])
    written = sum(1 for present in artifacts.values() if present)
    note = f"{written} proposal artifact(s) synced from disk"
    return f"{note} ({'; '.join(failed)})" if failed else note
