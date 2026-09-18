"""What an estimator may send to open or change a bid.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

Stage = Literal["intake", "extraction", "quote", "proposal"]


EstimateMode = Literal["one_off", "templated"]

# Whether CBC is quoting this job at all. `not_bid` is the spec's `noBid`
# status (collections.mongodb.md 3.21): a job that went unworked, held apart
# from Won and Lost so it is never counted as a loss.
BidStatus = Literal["bid", "not_bid"]

# How a bid ended. Entered by hand by the estimator - nothing derives it from
# P21, from the proposal, or from anything else. "" means still open, and is
# how a caller clears an outcome (`exclude_none` cannot carry a null).
Outcome = Literal["won", "lost", ""]

# The team the person who entered the bid sits on. A per-bid label, not an auth
# role - `users.role` stays `admin | estimator`.
EnteredByRole = Literal["Sales", "Estimating", "Purchasing", "Operations"]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # Run Phase 0-6 in one pass when a drawing lands, instead of stopping for the
    # estimator to confirm the openings before anything is priced. Opt-in per bid;
    # the default comes from the `pipeline` settings document.
    autopilot: bool | None = None
    # Matrix 3.0: one-off (Kevin) vs templated (Shanna). Rick's Excel is out of scope.
    mode: EstimateMode | None = None
    brand: str | None = None
    jobName: str | None = None
    location: str | None = None
    state: str | None = Field(default=None, max_length=2, description="Ship-to state; drives tax")
    architect: str | None = None
    gc: str | None = None
    initiator: str | None = None
    bidDue: date | None = None
    projectNumber: str | None = None
    # Phase 0: alternates noted at intake (names only; reconciliation is Matrix 4.1 Pending).
    bidAlternates: list[str] | None = None
    # FR-1: email / RFP text intake, not only PDF upload.
    intakeChannel: Literal["email", "phone", "manual"] | None = None
    rfpText: str | None = None
    sourceEmailMessageId: str | None = None
    # The team `initiator` sits on.
    enteredByRole: EnteredByRole | None = None
    # A user's email, or "" for unassigned. Email is the key because it is
    # already the auth identity and `users.email` is unique.
    assignedEstimator: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    autopilot: bool | None = None
    mode: EstimateMode | None = None
    brand: str | None = None
    jobName: str | None = None
    location: str | None = None
    state: str | None = Field(default=None, max_length=2)
    architect: str | None = None
    gc: str | None = None
    initiator: str | None = None
    bidDue: date | None = None
    projectNumber: str | None = None
    bidAlternates: list[str] | None = None
    stage: Stage | None = None
    enteredByRole: EnteredByRole | None = None
    assignedEstimator: str | None = None
    # Setting `not_bid` clears the outcome; setting an outcome forces `bid`.
    # Both transitions are recorded on `statusHistory` - see UpdateProject.
    bidStatus: BidStatus | None = None
    outcome: Outcome | None = None
    # The P21 order raised against a won bid. Closes the bid-to-order loop the
    # dashboard reports on.
    p21OrderNo: str | None = None
