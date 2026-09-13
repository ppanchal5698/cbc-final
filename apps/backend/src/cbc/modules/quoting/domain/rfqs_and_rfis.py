"""Vendor RFQs and RFIs: two of the operational collections the implementation never had.

    vendorRfqs      FR-16  the third cost path: request out, price back
    rfis            Phase 5 questions raised before finalizing

`VENDOR_RFQ` existed as a `CostSource` value with no way to set it, and the
string appears nowhere in the web app. Phase 5 had no collection at all, so its
RFIs lived as free text in the general-purpose `calls` log.

Shapes, enums and state machines are `docs/collections.mongodb.md` §3.28 and
§3.29, field for field.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# ── FR-16: the vendor RFQ loop (§3.28) ──────────────────────────────────────

RfqTrigger = Literal[
    "customSize", "unusualPrep", "notSoldInYears", "nonStock", "firstTime", "beyondCutoff"
]
RfqStatus = Literal["draft", "requested", "awaiting", "received", "applied", "expired", "cancelled"]

# §3.28: draft -> requested -> awaiting -> received -> applied, plus expiry from
# either waiting state and cancellation from anything not yet applied.
RFQ_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft": ("requested", "cancelled"),
    "requested": ("awaiting", "cancelled"),
    "awaiting": ("received", "expired", "cancelled"),
    "received": ("applied", "expired", "cancelled"),
    "applied": (),
    "expired": (),
    "cancelled": (),
}


class RfqItem(BaseModel):
    description: str | None = None
    partNumber: str | None = None
    quantity: float | None = None
    sizeCode: str | None = None
    finishCode: str | None = None
    options: dict[str, Any] | None = None
    estimateLineId: str | None = None


class RfqPrice(BaseModel):
    estimateLineId: str | None = None
    amount: float | None = None
    currency: str = "USD"
    validUntil: datetime | None = None
    leadTimeDays: int | None = None
    notes: str | None = None


class VendorRfq(BaseModel):
    """Matrix 6.6 notes an RFQ *can hold up a bid*, which is why `blocksBid`
    exists and why the chase list is indexed by due date."""

    rfqNumber: str
    bidRequestId: str
    vendorId: str | None = None
    triggerReason: RfqTrigger
    requestedItems: list[RfqItem] = Field(default_factory=list)
    status: RfqStatus = "draft"
    statusHistory: list[dict[str, Any]] = Field(default_factory=list)
    requestedAt: datetime | None = None
    requestedBy: str | None = None
    dueBy: datetime | None = None
    respondedAt: datetime | None = None
    responseDocumentId: str | None = None
    quotedPrices: list[RfqPrice] = Field(default_factory=list)
    blocksBid: bool = False
    notes: str | None = None


# ── Phase 5: RFIs (§3.29) ───────────────────────────────────────────────────

RfiCategory = Literal[
    "missingRating", "missingHanding", "missingFinish", "scopeAmbiguity",
    "substitutionApproval", "quantityAmbiguity", "other",
]
RfiStatus = Literal["open", "sent", "answered", "closed", "withdrawn"]

RFI_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "open": ("sent", "withdrawn"),
    "sent": ("answered", "withdrawn"),
    "answered": ("closed",),
    "closed": (),
    "withdrawn": (),
}


class Rfi(BaseModel):
    """Also where a direct-equal substitution approval is sought from the GC
    (Matrix 6.4) - the note on the line records what was proposed, this records
    whether anybody said yes."""

    bidRequestId: str
    rfiNumber: str
    subject: str
    question: str
    category: RfiCategory
    relatedOpeningIds: list[str] = Field(default_factory=list)
    relatedEstimateLineIds: list[str] = Field(default_factory=list)
    raisedBy: str | None = None
    raisedAt: datetime
    sentToParty: Literal["gc", "architect", "initiator", "vendor"] | None = None
    status: RfiStatus = "open"
    statusHistory: list[dict[str, Any]] = Field(default_factory=list)
    answer: str | None = None
    answeredAt: datetime | None = None
    blocksFinalization: bool = False


def next_states(transitions: dict[str, tuple[str, ...]], current: str) -> tuple[str, ...]:
    return transitions.get(current, ())


def check_transition(
    transitions: dict[str, tuple[str, ...]], current: str, target: str, *, label: str
) -> None:
    """Refuse an edge the specification does not draw."""
    if target not in transitions.get(current, ()):
        allowed = ", ".join(transitions.get(current, ())) or "nothing"
        raise ValueError(
            f"{label}: {current} -> {target} is not a transition; "
            f"{current} may go to: {allowed}"
        )
