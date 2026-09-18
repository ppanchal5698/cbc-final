"""The retired run_full_pipeline job: every phase, 0 to 6, in one Claude pass.

POST /api/jobs refuses it now - autopilot chains extract, price and propose as
separate jobs - but a job queued before it was retired still runs. It lives in
intake, the one module that may import every part it touches.
"""
from __future__ import annotations

import asyncio
from typing import Any

from cbc.modules.extraction.api import door_schedule, passes
from cbc.modules.intake.api import documents
from cbc.modules.ops.api import jobs as ops_jobs
from cbc.modules.projects.api import pipeline
from cbc.modules.quoting.api import priced_lines, proposal_artifacts, quote
from cbc.shared import events


async def run(job: dict[str, Any]) -> None:
    await pipeline.run_pass(job, sync=sync_results, prepare=passes.prepare, watch=passes.watch_progress)


async def sync_results(job: dict[str, Any], project: dict[str, Any] | None) -> str:
    note = await passes.check_output(job, project)
    if note is not None:
        return note
    openings = await door_schedule.import_extraction(project, job=job)
    if openings.get("aborted"):
        return "lease stolen; discarded output"
    await documents.mark_all_read(project["_id"])
    if not await ops_jobs.holds_lease(job):
        return "lease stolen; discarded output"
    priced = await priced_lines.import_quote_lines(project, job=job)
    if priced.get("aborted"):
        return "lease stolen; discarded output"
    await quote.persist(project)
    failed = await asyncio.to_thread(proposal_artifacts.render_artifacts, job["type"], project["slug"])
    artifacts = await proposal_artifacts.import_proposal_artifacts(project)
    await events.publish(events.QUOTE_COMPLETED, project_id=project["_id"])
    written = sum(1 for present in artifacts.values() if present)
    note = (
        f"{openings['inserted'] + openings['updated']} opening(s), "
        f"{priced['inserted'] + priced['updated']} priced line(s), "
        f"{written} proposal artifact(s) - draft ready for estimator review"
    )
    return f"{note} ({'; '.join(failed)})" if failed else note
