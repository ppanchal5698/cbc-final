"""What an estimator may send to freeze a version, and what every version response says is still open.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


PENDING_NOTE = (
    "How an addendum reconciles against the previous version, and whether an "
    "alternate inherits the base bid's confirmations, are still open questions "
    "(Matrix 4.1 / Open Item 11). Differences are flagged, never merged."
)


class VersionCreate(BaseModel):
    reason: str = Field(min_length=1, max_length=200, description="e.g. 'Addendum 1'")
    documentId: str | None = None
