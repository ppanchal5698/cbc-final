"""GET /api/jobs/dead - the dead-letter queue, with each job's bid named."""
from __future__ import annotations

from fastapi import APIRouter

from cbc.modules.ops.api import project_lookup
from cbc.modules.ops.infrastructure.collections import jobs as jobs_collection
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/dead")
async def list_dead_jobs(limit: int = 100) -> dict:
    """Dead-lettered jobs for the ops queue."""
    cap = min(max(limit, 1), 200)
    found = await jobs_collection().find({"status": "dead"}).sort("finishedAt", -1).to_list(cap)
    total = await jobs_collection().count_documents({"status": "dead"})
    project_ids = [job["projectId"] for job in found if job.get("projectId")]
    # Bids belong to the projects module; ops asks for their names through a port.
    names = await project_lookup.summaries(project_ids) if project_ids else {}
    rows = []
    for job in found:
        row = dict(job)
        project = names.get(job.get("projectId")) or {}
        row["projectCode"] = project.get("code")
        row["projectName"] = project.get("name")
        rows.append(row)
    return {"jobs": serialise(rows), "total": total}
