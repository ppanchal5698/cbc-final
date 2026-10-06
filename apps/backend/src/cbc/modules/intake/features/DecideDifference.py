"""POST /api/projects/{code}/versions/{version}/decisions - keep or revert one difference (FR-14).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from cbc.modules.intake.domain import versioning
from cbc.modules.intake.infrastructure import reconcile
from cbc.modules.intake.infrastructure.collections import versions
from cbc.modules.ops.api import audit
from cbc.modules.projects.api.lookup import load
from cbc.shared.auth import Actor

router = APIRouter(prefix="/api/projects/{code}", tags=["versions"])


class Decision(BaseModel):
    kind: Literal["opening", "line"]
    key: str = Field(min_length=1, max_length=200)
    decision: Literal["keep", "revert"]


@router.post("/versions/{version}/decisions")
async def decide_difference(code: str, version: int, body: Decision, actor: Actor) -> dict:
    """Requirements 6.4: the estimator accepts the diff line by line. Keeping a
    difference leaves the bid as it is; reverting it puts the version's back. When
    no difference is left undecided, the version is reconciled."""
    project = await load(code)
    stored = await versions().find_one({"projectId": project["_id"], "version": version})
    if stored is None:
        raise HTTPException(404, f"version {version} not found")
    try:
        versioning.guard_writable(stored)
    except versioning.VersionLocked as exc:
        raise HTTPException(409, str(exc)) from exc

    found = await reconcile.rows(project, stored)
    row = next((r for r in found if r["kind"] == body.kind and r["key"] == body.key), None)
    if row is None:
        raise HTTPException(404, f"no {body.kind} {body.key!r} differs from version {version}")
    if body.decision == "revert":
        await reconcile.revert(project, stored, body.kind, body.key, actor)

    now = datetime.now(timezone.utc)
    entry = {"kind": body.kind, "key": body.key, "change": row["change"], "decision": body.decision,
             "by": actor, "at": now}
    await versions().update_one({"_id": stored["_id"]}, {"$push": {"decisions": entry}})
    stored = await versions().find_one({"_id": stored["_id"]}) or stored
    remaining = reconcile.undecided(await reconcile.rows(project, stored))
    if not remaining:
        await versions().update_one(
            {"_id": stored["_id"], "lockedAt": None},
            {"$set": {"reconciled": True, "reconciledBy": actor, "reconciledAt": now}},
        )
    await audit.record("version.decision", actor, {"projectId": project["_id"]},
                       after={"version": version, **{k: v for k, v in entry.items() if k != "at"}})
    return {"version": version, "kind": body.kind, "key": body.key, "decision": body.decision,
            "undecided": len(remaining), "reconciled": not remaining}
