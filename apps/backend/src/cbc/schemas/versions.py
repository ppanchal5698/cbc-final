from __future__ import annotations

from pydantic import BaseModel, Field


class AlternateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60, description="e.g. 'Alternate 1'")


class AlternateAssign(BaseModel):
    ids: list[str] = Field(min_length=1)
    alternate: str | None = None
    scope: str = Field(default="line-items", pattern="^(line-items|quote-lines)$")

