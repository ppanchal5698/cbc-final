"""POST /api/projects/{code}/proposal/complete - approve and route to the sales initiator. Nothing is sent.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from cbc.modules.ops.api import audit
from cbc.modules.projects.api import bids
from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.api import approvals, quote as quote_service
from cbc.modules.quoting.domain.quotes import HandOff
from cbc.modules.quoting.infrastructure.collections import proposals
from cbc.modules.quoting.infrastructure.proposal_view import (
    DEFAULT_EXCLUSIONS,
    VALIDITY_DAYS,
    export_for_review,
    proposal_payload,
    write_email_draft,
)
from cbc.modules.quoting.domain import proposals as proposal_rules
from cbc.shared import events
from cbc.shared.auth import Actor

router = APIRouter(prefix="/api/projects/{code}/proposal", tags=["proposal"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/complete")
async def mark_complete(code: str, actor: Actor, body: HandOff | None = None) -> dict:
    """Sign off and route the bid to the sales initiator - inside this app only.

    NFR-1 is untouched: the estimator approves, the bid appears in the named
    person's queue, and the drafted body is written to disk for them to send.
    Nothing is transmitted from here, by any means.
    """
    project = await load(code)
    recipient = (body.recipient if body else None) or project.get("initiator")

    # The gate. A lapsed sheet means the margin on those lines is not real, so
    # the hand-off waits for purchasing or for a recorded override; a blocking
    # review flag waits for the estimator to clear what it names. Exported first so the flags see the latest edits.
    await export_for_review(project)
    readiness = (await proposal_payload(project))["readiness"]
    if readiness.get("blocking"):
        raise HTTPException(status_code=409, detail=readiness["note"])

    # This call *is* the estimator's approval, so it is where §3.30's required
    # `approvedBy` gets its value - a named person, never a system actor. Before
    # this the field did not exist and the only trace was a signoff entry the
    # hand-off pushed for itself, which is not an approval by anyone.
    totals, _lines = await quote_service.totals_for(project)
    stored = await proposals().find_one({"projectId": project["_id"]})
    approval = proposal_rules.approve(
        approved_by=actor,
        totals=totals,
        terms={
            "validityDays": VALIDITY_DAYS,
            "poRequired": True,
            "supplyOnly": True,
            "exclusions": (stored or {})["exclusions"] if (stored or {}).get("exclusions") is not None
            else DEFAULT_EXCLUSIONS,
        },
    )

    # Each approval of a changed bid is an issue (FR-14): the first is the
    # original; one after an addendum or a new version is the next revision,
    # approved afresh, and supersedes the last. Routing the same proposal to
    # someone else is not a new issue.
    issues = (stored or {}).get("issues") or []
    revised = proposal_rules.revised_since_issue(project, stored or {})
    issue = {"revision": len(issues), "at": _now(), "by": actor, "recipient": recipient,
             "version": project.get("version")}  # the latest frozen version; None before the first

    # A proposal cannot come into existence via hand-off upsert (NFR-1 / §3.30).
    # Approval is an insert (or a stamp onto an existing draft); hand-off then
    # updates without upsert.
    if stored is None:
        await proposals().insert_one(
            {
                "projectId": project["_id"],
                **approval,
                "createdAt": _now(),
                "issues": [issue],
            }
        )
    else:
        changes: dict = {}
        if not stored.get("approvedBy") or revised:
            changes.update(approval)
        if not issues or revised:
            # The whole list in one write: Mongo will not set into an array and
            # push onto it in the same update.
            changes["issues"] = [*issues[:-1], {**issues[-1], "supersededAt": _now()}, issue] if issues else [issue]
        if changes:
            await proposals().update_one({"_id": stored["_id"]}, {"$set": changes})

    await proposals().update_one(
        {"projectId": project["_id"]},
        {
            "$set": {
                "completedAt": _now(),
                "completedBy": actor,
                "handedOffTo": recipient,
                "handOffNote": body.note if body else None,
            },
            "$push": {
                "signoff": {"role": "estimator", "by": actor, "at": _now(), "state": "complete"}
            },
        },
    )
    await bids.record_hand_off(project["_id"], recipient)

    draft_path = await write_email_draft(project, recipient, actor)

    await audit.record(
        "proposal.hand_off",
        actor,
        {"projectId": project["_id"]},
        after={"recipient": recipient},
        note="in-app hand-off; nothing transmitted",
    )
    # Whoever learns from approved bids hears it here. A listener's failure must
    # not undo a sign-off that is already stored, so listeners catch their own.
    await events.publish(approvals.PROPOSAL_APPROVED, project_id=project["_id"], approved_by=actor)
    return {
        "status": "complete",
        "sent": False,
        "handedOffTo": recipient,
        "draftPath": draft_path,
        # Both branches say it, because "nothing has been sent" is the thing the
        # estimator needs to read back on every hand-off (NFR-1).
        "message": (
            f"Signed off and routed to {recipient}. Nothing has been sent."
            if recipient
            else "Signed off, but no sales initiator is recorded on this bid, "
            "so there is nobody to route it to. Nothing has been sent."
        ),
    }
