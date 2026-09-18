"""PATCH /api/projects/{code} - change a bid's details or move its stage.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from cbc.modules.ops.api import audit
from cbc.modules.projects.api.lookup import load
from cbc.modules.projects.domain.bid import ProjectUpdate
from cbc.modules.projects.infrastructure.board import decorate
from cbc.modules.projects.infrastructure.collections import bid_requests
from cbc.shared.auth import Actor

router = APIRouter(prefix="/api/projects", tags=["projects"])


STAGE_PROGRESS = {"intake": 0, "extraction": 33, "quote": 67, "proposal": 100}


def _apply_bid_state(changes: dict, project: dict) -> list[dict]:
    """Reconcile bid status against outcome, and say what changed.

    Two rules, both the estimator's own: a job marked Not bid has no outcome,
    and recording an outcome means it was bid after all. Returns the
    `statusHistory` entries to append - collections.mongodb.md 3.21 names that
    field as what hit rate is meant to be aggregated from, and until now
    nothing wrote it.
    """
    if changes.get("bidStatus") == "not_bid":
        changes["outcome"] = ""
    if changes.get("outcome"):
        changes["bidStatus"] = "bid"

    entries = []
    for field in ("bidStatus", "outcome"):
        if field not in changes:
            continue
        before = project.get(field) or ""
        after = changes[field] or ""
        if before != after:
            entries.append({"field": field, "from": before, "to": after})
    return entries


@router.patch("/{code}")
async def update_project(code: str, body: ProjectUpdate, actor: Actor) -> dict:
    project = await load(code)
    changes = body.model_dump(exclude_none=True)
    if not changes:
        return await decorate(project)

    if "bidDue" in changes and changes["bidDue"]:
        changes["bidDue"] = datetime.combine(
            changes["bidDue"], datetime.min.time(), tzinfo=timezone.utc
        )
    if "bidAlternates" in changes:
        changes["bidAlternates"] = [
            str(a).strip() for a in (changes["bidAlternates"] or []) if str(a).strip()
        ]
    if "stage" in changes:
        changes["progress"] = STAGE_PROGRESS.get(changes["stage"], project.get("progress", 0))
    transitions = _apply_bid_state(changes, project)
    now = datetime.now(timezone.utc)
    changes["updatedAt"] = now

    update: dict = {"$set": changes}
    if transitions:
        update["$push"] = {
            "statusHistory": {
                "$each": [{**t, "at": now, "by": actor, "note": None} for t in transitions]
            }
        }
    await bid_requests().update_one({"_id": project["_id"]}, update)
    await audit.record(
        "project.update",
        actor,
        {"projectId": project["_id"]},
        before={k: project.get(k) for k in changes},
        after=changes,
    )
    return await decorate(await bid_requests().find_one({"_id": project["_id"]}))
