"""Estimator corrections and FRP take-offs: two of the operational collections the implementation never had.

    takeoffs        FR-12  FRP geometry - perimeter, corners, wall height
    feedbackEvents  FR-13  estimator corrections, structured

`feedbackEvents` appeared only as an unfilled `"estimatorCorrections": None`
placeholder. Shapes and enums are `docs/collections.mongodb.md` §3.24 and §3.31,
field for field.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# ── FR-13: estimator corrections (§3.31) ────────────────────────────────────

FeedbackType = Literal[
    "matchRejected", "matchCorrected", "costOverridden", "marginOverridden",
    "lineAdded", "lineDeleted", "extractionCorrected", "substitutionMade",
]


class FeedbackEvent(BaseModel):
    """The structured record of every correction, which is what makes
    improvement measurable rather than anecdotal (FR-13).

    `matchConfidenceAtTime` is the field that earns its keep: it says what the
    copilot claimed when it turned out to be wrong, so confidence can be
    calibrated against outcomes instead of asserted.
    """

    bidRequestId: str
    estimateLineId: str | None = None
    openingId: str | None = None
    eventType: FeedbackType
    field: str | None = None
    proposedValue: dict[str, Any] | None = None
    correctedValue: dict[str, Any] | None = None
    proposedCatalogItemId: str | None = None
    correctedCatalogItemId: str | None = None
    matchConfidenceAtTime: float | None = None
    reason: str | None = None
    userId: str | None = None
    occurredAt: datetime
    appliedToLearning: bool = False


# ── FR-12: FRP take-off geometry (§3.24) ────────────────────────────────────


class Takeoff(BaseModel):
    """Vu360 gives geometry only; the estimator converts to quantities by hand.

    `constantsUsed` is deliberately nullable and stays null: the FRP conversion
    constants are Open Item 5 and CBC has not provided them. A take-off that
    records geometry and says the conversion is still owed is the honest
    artifact; one that invents panel counts is not.
    """

    bidRequestId: str
    takeoffType: Literal[
        "frp", "frpArea", "count", "linear", "accessoryCount", "div10", "openingCount", "other"
    ] = "frp"
    perimeterLf: float | None = None
    insideCorners: int | None = None
    outsideCorners: int | None = None
    wallHeightFt: float | None = None
    drawingScale: str | None = None
    productType: str | None = None
    manufacturer: str | None = None
    location: str | None = None
    drawingRef: str | None = None
    qty: float | None = None
    unit: str | None = None
    specifiedModel: str | None = None
    finish: str | None = None
    vu360Notes: str | None = None
    panelRequirements: str | None = None
    trimRequirements: str | None = None
    adhesiveRequirements: str | None = None
    specialConditions: str | None = None
    constantsUsed: dict[str, Any] | None = None
    quantities: dict[str, Any] | None = None
    status: Literal["measured", "converted", "pendingConstants", "NOT_MEASURED", "NOT_EXTRACTED"] = (
        "pendingConstants"
    )
    sourceRef: dict[str, Any] | None = None
    flags: list[str] = Field(default_factory=list)
    notes: str | None = None
