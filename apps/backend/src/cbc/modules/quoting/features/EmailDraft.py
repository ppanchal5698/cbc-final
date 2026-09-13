"""GET /api/projects/{code}/proposal/email-draft - the body to copy into a mail client. The system does not send.
"""
from __future__ import annotations

from fastapi import APIRouter

from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.infrastructure.collections import proposals
from cbc.modules.quoting.infrastructure.proposal_view import NEWLINE, VALIDITY_DAYS, proposal_payload

router = APIRouter(prefix="/api/projects/{code}/proposal", tags=["proposal"])


@router.get("/email-draft")
async def email_draft(code: str) -> dict:
    """The prepared body, for the estimator to copy into their own mail client."""
    project = await load(code)
    data = await proposal_payload(project)
    stored = await proposals().find_one({"projectId": project["_id"]}) or {}

    flags = []
    if data["readiness"]["flaggedLineItems"]:
        flags.append(f"{data['readiness']['flaggedLineItems']} extracted line(s) still flagged")
    if data["readiness"]["unpricedQuoteLines"]:
        flags.append(f"{data['readiness']['unpricedQuoteLines']} line(s) need a manual price")

    body = NEWLINE.join(
        [
            f"Hi {(stored.get('handedOffTo') or project.get('initiator') or 'there').split()[0]},",
            "",
            f"Quotation {data['proposal']['proposalNo']} for {project.get('name')} is ready.",
            "",
            f"- Total: ${data['totals']['grandTotal']:,.2f}",
            f"- Supply-only material. HP purchase order required. Valid {VALIDITY_DAYS} days.",
            "- Freight: TBD, handled when the quote becomes a job.",
            *(["", "Needs attention before it goes out:"] if flags else []),
            *[f"- {flag}" for flag in flags],
            "",
            "Thanks,",
            stored.get("completedBy") or "CBC Estimating",
        ]
    )

    return {
        "to": stored.get("handedOffTo") or project.get("initiator"),
        "subject": f"CBC Quotation {data['proposal']['proposalNo']} - {project.get('name')}",
        "body": body,
        "sent": False,
        "note": "Copy this into your own mail client. The system does not send (NFR-1).",
    }
