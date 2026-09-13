"""DELETE /api/projects/{code} - remove a bid, its rows in every module, and its files.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Response

from cbc.modules.ops.api import audit, jobs as ops_jobs
from cbc.modules.projects.api import bids
from cbc.modules.projects.api.lookup import load
from cbc.modules.projects.infrastructure.collections import bid_requests, calls
from cbc.shared import storage
from cbc.shared import events
from cbc.shared.auth import AdminActor

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.delete("/{code}", status_code=204, response_class=Response)
async def delete_project(code: str, actor: AdminActor) -> Response:
    """Remove the bid record and all files under projects/{slug}/.

    Admin-only. Cancels outstanding jobs, purges Mongo child collections and
    job history, then deletes the project directory from disk.
    """
    project = await load(code)
    project_id = project["_id"]
    slug = project.get("slug") or ""

    await ops_jobs.cancel_active_for_project(project_id, actor, note="project deleted")
    await calls().delete_many({"projectId": project_id})
    # Every module that keeps rows for a bid deletes its own when it hears this.
    await events.publish(bids.PROJECT_DELETED, project_id=project_id)
    await ops_jobs.delete_for_project(project_id)
    await bid_requests().delete_one({"_id": project_id})

    try:
        if slug:
            await asyncio.to_thread(storage.purge_project, slug)
    except OSError as exc:
        raise HTTPException(
            500,
            detail=(
                f"{project.get('code')} was removed from the board but its files "
                f"could not be deleted from disk: {exc}. Ask an operator to remove "
                f"projects/{slug}/ manually."
            ),
        ) from exc

    await audit.record(
        "project.delete",
        actor,
        {"projectId": project_id},
        before=project.get("code"),
        note="database and project files purged",
    )
    return Response(status_code=204)
