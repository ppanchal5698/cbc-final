from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class Document(BaseModel):
    id: str
    projectId: str
    filename: str
    kind: Literal["plan", "spec", "rfp", "addendum", "other"] = "plan"
    pages: int | None = None
    bytes: int | None = None
    path: str
    contentSha: str | None = None
    state: Literal["received", "reading", "read", "failed"] = "received"
    uploadedAt: datetime
