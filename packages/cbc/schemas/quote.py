from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from cbc.schemas.common import CostSource, ProductType


class QuoteLineBase(BaseModel):
    part: str | None = None
    description: str = ""
    division: str | None = None
    qty: float = Field(default=1, ge=0)
    cost: float | None = Field(default=None, ge=0)
    margin: float | None = Field(default=None, ge=0.0, lt=1.0)
    productType: ProductType | None = None
    basis: str | None = "Book price"


class QuoteLineCreate(QuoteLineBase):
    lineItemId: str | None = None
    productId: str | None = None
    alternateGroup: str | None = None


class QuoteLineUpdate(BaseModel):
    description: str | None = None
    # Bounded because calc-engine rejects a negative cost, and `_recompute` walks
    # every line: one typed "-45" turned the whole quote and proposal into a 400
    # with no screen left to correct it from.
    qty: float | None = Field(default=None, ge=0)
    cost: float | None = Field(default=None, ge=0)
    margin: float | None = Field(default=None, ge=0.0, lt=1.0)
    basis: str | None = None
    overrideReason: str | None = None


class QuoteLine(QuoteLineBase):
    id: str
    projectId: str
    alternateGroup: str | None = None
    lineItemId: str | None = None
    sell: float | None = None
    extended: float | None = None
    costSource: CostSource | None = None
    costSourceDetail: str | None = None
    multiplier: float | None = None
    multiplierTier: str | None = None
    multiplierEffectiveDate: str | None = None
    priceBookVersion: str | None = None
    sourcePage: int | None = None
    addedByHand: bool = False
    marginOverridden: bool = False
    overrideReason: str | None = None
    priceStatus: str | None = None
    flags: list[str] = []


class QuoteSettings(BaseModel):
    taxJurisdiction: str | None = Field(default=None, description="Two-letter state, e.g. OH")
    freight: float | None = None
    freightNote: str | None = None


class QuoteTotals(BaseModel):
    subtotal: float
    margin: float | None = None
    taxRate: float
    tax: float
    freight: float | None = None
    freightNote: str | None = None
    grandTotal: float
    taxJurisdiction: str | None = None
    taxNote: str | None = None
    groups: list[dict[str, Any]] = []


class ProposalSettings(BaseModel):
    markup: float = Field(default=0.0, ge=0.0, le=0.25)
    customer: dict[str, Any] | None = None
    salesRep: dict[str, Any] | None = None
    estimator: dict[str, Any] | None = None
    exclusions: list[str] | None = None


class HandOff(BaseModel):
    """Route a finished bid to the sales initiator. Records; never transmits."""

    recipient: str | None = Field(default=None, description="Defaults to the project initiator")
    note: str | None = None
