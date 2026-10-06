"""GET /api/projects/{code}/proposal/email-draft - the body to copy into a mail client. The system does not send.
"""
from __future__ import annotations

from fastapi import APIRouter

from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.infrastructure.collections import proposals
from cbc.modules.quoting.infrastructure.proposal_view import email_draft, proposal_payload

router = APIRouter(prefix="/api/projects/{code}/proposal", tags=["proposal"])


@router.get("/email-draft")
async def get_email_draft(code: str) -> dict:
    """The prepared body, for the estimator to copy into their own mail client -
    the same draft the sign-off files and the build job writes."""
    project = await load(code)
    stored = await proposals().find_one({"projectId": project["_id"]}) or {}
    draft = email_draft(project, await proposal_payload(project, internal=True),
                        recipient=stored.get("handedOffTo"), estimator=stored.get("completedBy"))
    return {
        "to": draft["to"],
        "subject": draft["subject"],
        "body": draft["body"],
        "sent": False,
        "note": "Copy this into your own mail client. The system does not send (NFR-1).",
    }
