"""What purchasing may send to open or change a price book.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class PriceBookBase(BaseModel):
    vendor: str = Field(min_length=1)
    program: str | None = None
    multiplier: float | None = None
    categories: dict[str, float] | None = None
    effective: str | None = None
    protectedThrough: str | None = None
    lastReviewed: str | None = None
    steward: str | None = None
    kind: str | None = "price_book"
    note: str | None = None


class PriceBookCreate(PriceBookBase):
    pass


class PriceBookUpdate(BaseModel):
    program: str | None = None
    multiplier: float | None = None
    categories: dict[str, float] | None = None
    effective: str | None = None
    protectedThrough: str | None = None
    lastReviewed: str | None = None
    steward: str | None = None
    note: str | None = None
