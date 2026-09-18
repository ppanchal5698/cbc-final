"""PATCH /api/projects/{code}/proposal - markup, customer, rep, estimator and exclusions.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter

from cbc.modules.ops.api import audit
from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.domain.quotes import ProposalSettings
from cbc.modules.quoting.infrastructure.collections import proposals
from cbc.modules.quoting.infrastructure.proposal_view import proposal_payload
from cbc.shared.auth import Actor

router = APIRouter(prefix="/api/projects/{code}/proposal", tags=["proposal"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.patch("")
async def update_proposal(code: str, body: ProposalSettings, actor: Actor) -> dict:
    project = await load(code)
    changes = body.model_dump(exclude_unset=True)

    # An override is a person, not a flag: store who, so the trail answers
    # "who said this lapsed price was fine" months later (auditability.md).
    if changes.pop("acknowledgeLapsed", None) is not None:
        changes["lapsedAcknowledgedBy"] = actor
        changes["lapsedAcknowledgedAt"] = _now()

    await proposals().update_one(
        {"projectId": project["_id"]},
        {
            "$set": {**changes, "updatedAt": _now()},
            "$setOnInsert": {
                "projectId": project["_id"],
                "proposalNo": f"Q-{project['code'].split('-')[-1]}",
                "date": date.today().isoformat(),
                "createdAt": _now(),
            },
        },
        upsert=True,
    )
    await audit.record("proposal.update", actor, {"projectId": project["_id"]}, after=changes)
    return await proposal_payload(project)
