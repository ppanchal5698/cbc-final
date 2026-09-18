"""What an estimator may send to change a quote or a proposal, and to hand it off.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from cbc.modules.pricing.api.pricing import ProductType


CostSource = Literal[
    "P21_LAST_PO",
    "LIST_X_MULTIPLIER",
    "SPECIAL_NET",
    "VENDOR_RFQ",
    "DISTRIBUTOR_MANUAL",
    "MANUAL",
    "BOOK_PRICE",
]


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
    # FR-16. `VENDOR_RFQ` has been in the CostSource enum since the beginning
    # with no way for an estimator to set it: this model exposed qty, cost,
    # margin, basis and overrideReason and nothing else, so a line "awaiting
    # vendor quote" could not be marked as one and the returned price arrived as
    # an anonymous cost edit. Matrix 6.6 notes an outstanding RFQ can hold up a
    # bid, which it cannot do if nothing records that one is outstanding.
    costSource: CostSource | None = None
    costSourceDetail: str | None = None


class QuoteSettings(BaseModel):
    taxJurisdiction: str | None = Field(default=None, description="Two-letter state, e.g. OH")
    freight: float | None = None
    freightNote: str | None = None


class ProposalSettings(BaseModel):
    markup: float = Field(default=0.0, ge=0.0, le=0.25)
    customer: dict[str, Any] | None = None
    salesRep: dict[str, Any] | None = None
    estimator: dict[str, Any] | None = None
    exclusions: list[str] | None = None
    # Take responsibility for lines priced off a sheet past its review window,
    # instead of waiting for purchasing to confirm the cost. Stamped with the
    # actor's name, never a bare boolean - the point is who decided.
    acknowledgeLapsed: bool | None = None


class HandOff(BaseModel):
    """Route a finished bid to the sales initiator. Records; never transmits."""

    recipient: str | None = Field(default=None, description="Defaults to the project initiator")
    note: str | None = None
