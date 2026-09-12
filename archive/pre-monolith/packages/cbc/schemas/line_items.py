from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from cbc.schemas.common import Evidence, LineStatus


class LineItemBase(BaseModel):
    mark: str | None = None
    description: str = ""
    size: str | None = None
    qty: float = 1
    hwSet: str | None = None
    division: str | None = None
    handing: str | None = None
    finish: str | None = None
    fireRating: str | None = None
    frameType: str | None = None
    wallType: str | None = None
    # Derived from wallType against the five standard throats, never typed twice.
    frameDepth: str | None = None
    notes: str | None = None


class LineItemCreate(LineItemBase):
    productId: str | None = None
    part: str | None = None
    alternateGroup: str | None = None


class LineItemUpdate(BaseModel):
    mark: str | None = None
    description: str | None = None
    size: str | None = None
    qty: float | None = None
    hwSet: str | None = None
    division: str | None = None
    handing: str | None = None
    finish: str | None = None
    fireRating: str | None = None
    frameDepth: str | None = None
    status: LineStatus | None = None
    notes: str | None = None
    alternateGroup: str | None = None


class LineItem(LineItemBase):
    id: str
    projectId: str
    alternateGroup: str | None = None
    status: LineStatus = "needs_look"
    confidence: float | None = None
    flags: list[str] = []
    evidence: Evidence | None = None
    duplicateOf: str | None = None
    duplicateReason: str | None = None
    addedByHand: bool = False
    confirmedBy: str | None = None
    confirmedAt: datetime | None = None
    createdAt: datetime | None = None


class BulkAction(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)
    action: Literal["confirm", "delete"]
