from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from cbc.schemas.common import Stage

EstimateMode = Literal["one_off", "templated"]
ChainState = Literal[
    "idle",
    "extracting",
    "extraction_done",
    "extraction_needs_review",
    "pricing",
    "pricing_failed",
    "quoting",
    "quoting_failed",
    "complete",
    "awaiting_manual_retry",
    "dead",
]


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


class Project(ProjectCreate):
    id: str
    code: str
    slug: str
    stage: Stage = "intake"
    progress: int = 0
    # Which phase an autopilot run is in, for the board while it works.
    phase: str | None = None
    chainState: ChainState | None = None
    # Provenance for create-form fields filled from the bid PDF.
    intakeFieldSources: dict[str, dict] | None = None
    createdAt: datetime
    updatedAt: datetime | None = None
