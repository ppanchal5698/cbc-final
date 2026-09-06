"""What a proposal must carry before it can exist, and what it must freeze.

`collections.mongodb.md` §3.30 marks `approvedBy` **required**, with the note that
"a proposal cannot exist without a human approval". That is the specification's
one schema-level enforcement of NFR-1 - *the copilot drafts, sources, and
calculates; it does not send* - and it was the field that did not exist.

What stood in its place was a `signoff[]` entry pushed by the hand-off handler
itself, on an `upsert=True` write. So handing a proposal off *created* the
proposal document: no approval step preceded it, and nothing recorded who took
responsibility for the number that went to a customer.

The two snapshots are the other half. `termsSnapshot` and `totalsSnapshot` were
read live - `VALIDITY_DAYS` is a module constant and totals are recomputed on
every render - so a proposal already in a customer's hands renders differently
after any later line edit. §4.8 again: these are not caches.

This module is the rule. Applying it to the router is the router's job; keeping
it here means the rule can be read, and tested, without a web server.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

# §3.30. `generated` is where an approved proposal starts; there is no state
# before it, because an unapproved proposal is not a proposal.
STATUSES = ("generated", "sent", "superseded", "withdrawn")


class ApprovalRequired(Exception):
    """Raised when something tries to act on a proposal nobody approved."""


def now() -> datetime:
    return datetime.now(timezone.utc)


def approve(
    *,
    approved_by: Any,
    totals: dict[str, Any],
    terms: dict[str, Any],
    at: datetime | None = None,
) -> dict[str, Any]:
    """The fields a proposal comes into existence with.

    `approved_by` is not optional and not defaultable. A system actor cannot
    stand in for it: NFR-1 says no estimate reaches a customer without explicit
    estimator approval, and "explicit" is a person's name.
    """
    if not approved_by:
        raise ApprovalRequired(
            "a proposal needs the human who approved it (NFR-1); "
            "nothing may generate one on its own"
        )
    moment = at or now()
    return {
        "status": "generated",
        "approvedBy": approved_by,
        "approvedAt": moment,
        "generatedAt": moment,
        # Deep copies, because the caller's dicts keep changing - that is the
        # whole point of a snapshot (§4.8).
        "totalsSnapshot": deepcopy(totals),
        "termsSnapshot": deepcopy(terms),
        "sentAt": None,
        "sentToEmail": None,
        "deliveryChannel": None,
        "supersededByProposalId": None,
        "statusHistory": [],
    }


def guard_approved(proposal: dict[str, Any]) -> None:
    """Refuse to act on a proposal that no person approved."""
    if not (proposal or {}).get("approvedBy"):
        raise ApprovalRequired(
            "this proposal has no approvedBy. A signoff entry written by the "
            "hand-off itself is not an approval - the estimator approves first "
            "(NFR-1), and only then is there something to hand off"
        )


def mark_sent(
    proposal: dict[str, Any],
    *,
    to: str | None,
    channel: str,
    actor: Any,
    at: datetime | None = None,
) -> dict[str, Any]:
    """Record delivery. Nothing here transmits anything.

    `channel` says how it left - today always a draft written to disk for the
    initiating salesperson to send themselves, which is what NFR-1 requires and
    what `pre_send_quote.py` blocks any other route to.
    """
    guard_approved(proposal)
    moment = at or now()
    return {
        **proposal,
        "status": "sent",
        "sentAt": moment,
        "sentToEmail": to,
        "deliveryChannel": channel,
        "statusHistory": [
            *proposal.get("statusHistory", []),
            {"from": proposal.get("status"), "to": "sent", "at": moment, "by": actor},
        ],
    }


def supersede(
    proposal: dict[str, Any], *, by_id: Any, at: datetime | None = None
) -> dict[str, Any]:
    """A re-issue replaces this one; the original stays exactly as it was sent."""
    moment = at or now()
    return {
        **proposal,
        "status": "superseded",
        "supersededByProposalId": by_id,
        "statusHistory": [
            *proposal.get("statusHistory", []),
            {"from": proposal.get("status"), "to": "superseded", "at": moment, "by": None},
        ],
    }
