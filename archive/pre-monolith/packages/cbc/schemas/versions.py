from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AlternateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60, description="e.g. 'Alternate 1'")


class AlternateAssign(BaseModel):
    ids: list[str] = Field(min_length=1)
    alternate: str | None = None
    scope: str = Field(default="line-items", pattern="^(line-items|quote-lines)$")


class VersionCreate(BaseModel):
    reason: str = Field(min_length=1, max_length=200, description="e.g. 'Addendum 1'")
    documentId: str | None = None


class EstimateVersion(BaseModel):
    id: str
    projectId: str
    version: int
    reason: str
    createdAt: datetime
    createdBy: str
    lineItemCount: int
    quoteLineCount: int
    reconciled: bool = False
