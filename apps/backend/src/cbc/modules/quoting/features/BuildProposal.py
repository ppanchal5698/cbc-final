"""The build_proposal job: the draft quotation and its review pack.

Two engines, chosen in Settings > Pipeline:

- **v2** builds it in code: the quotation exactly as the proposal screen renders
  it (`proposal_view`), filed with the review flags, the review sheet, the email
  draft and the PDF. No pass, and no gate that fails the job over what the bid
  still lacks - the estimator's approval (MarkComplete) holds that.
- **legacy** is a Claude pass, after which the scripts render the quotation and
  review summary whatever it wrote.

Either way the artifacts are recorded on the proposal, and QUOTE_COMPLETED ends
the bid's saga at `complete`, in projects - a draft for the estimator, never a
sent quote (NFR-1).
"""
from __future__ import annotations

import asyncio
from typing import Any

from cbc.modules.extraction.api import passes
from cbc.modules.extraction.api.validation.artifacts import check_delivery_readiness
from cbc.modules.ops.api import jobs as ops_jobs
from cbc.modules.ops.api import pipeline as ops_pipeline
from cbc.modules.ops.api import worker as ops_worker
from cbc.modules.projects.api import lookup, pipeline
from cbc.modules.quoting.api import proposal_artifacts
from cbc.modules.quoting.infrastructure import proposal_view
from cbc.shared import events


async def run(job: dict[str, Any]) -> None:
    if await ops_pipeline.proposal_engine() == "v2":
        await pipeline.run_pass(job, sync=sync_results, work=build_in_code)
        return
    await pipeline.run_pass(job, sync=sync_results, prepare=_prepare)


async def build_in_code(job: dict[str, Any], project: dict[str, Any]) -> str:
    """The v2 proposal: the document the estimator approves, written where the
    pass's went - from the quote as it stands in Mongo, estimator edits and all."""
    project = await lookup.get(project["_id"]) or project
    data = await proposal_view.proposal_payload(project, internal=True)
    html = await asyncio.to_thread(proposal_view.render_html, project, data, False)
    email = await proposal_view.addressed_draft(project, data)
    if not await ops_jobs.holds_lease(job):
        return "lease stolen; discarded output"
    failed = await asyncio.to_thread(
        proposal_artifacts.render_in_code, job["type"], project["slug"], html, email["document"])
    artifacts = await proposal_artifacts.import_proposal_artifacts(project)
    await events.publish(events.QUOTE_COMPLETED, project_id=project["_id"])
    written = sum(1 for present in artifacts.values() if present)
    note = f"proposal built in code: {written} artifact(s)"
    return f"{note} ({'; '.join(failed)})" if failed else note


async def _prepare(job: dict[str, Any], project: dict[str, Any], payload: dict[str, Any]) -> bool:
    problems, _ = await asyncio.to_thread(check_delivery_readiness, project["slug"])
    if not problems:
        return True
    await ops_worker.finish(
        job, False, "Delivery blocked: " + "; ".join(problems), "",
        permanent=True, error_code="artifact_validation",
    )
    return False


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
