from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AuditEntry(BaseModel):
    id: str
    at: datetime
    actor: str
    action: str
    target: dict[str, Any] = Field(default_factory=dict)
    before: Any = None
    after: Any = None
    note: str | None = None
