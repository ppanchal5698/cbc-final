"""What an estimator may send to freeze a version, and what every version response says is still open.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


PENDING_NOTE = (
    "Each difference is the estimator's to keep or revert (requirements 6.4, "
    "Matrix 4.1); nothing is merged on its own. Whether an alternate inherits the "
    "base bid's confirmations is still open (Open Item 11)."
)


class VersionCreate(BaseModel):
    reason: str = Field(min_length=1, max_length=200, description="e.g. 'Addendum 1'")
    documentId: str | None = None
