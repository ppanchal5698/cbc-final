"""A catalog part: what an estimator may send, and the sell price it implies.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from cbc.schemas.common import ProductType
from cbc.modules.pricing.api import pricing
from cbc.shared.mongo import oid


PriceBasis = Literal["list", "net", "unknown"]


class ProductBase(BaseModel):
    part: str = Field(min_length=1)
    description: str = ""
    manufacturer: str | None = None
    division: str | None = None
    cost: float | None = None
    listPrice: float | None = None
    # What `listPrice` means for this row. A "net" part is never repriced by a
    # program multiplier - multiplying a cost discounts it twice.
    priceBasis: PriceBasis | None = None
    multiplier: float | None = None
    sellAt: float | None = None
    availability: str | None = None
    priceBookId: str | None = None
    priceBook: str | None = None
    xref: list[dict[str, str]] = []
    productType: ProductType | None = None


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    description: str | None = None
    manufacturer: str | None = None
    division: str | None = None
    cost: float | None = None
    listPrice: float | None = None
    priceBasis: PriceBasis | None = None
    multiplier: float | None = None
    sellAt: float | None = None
    availability: str | None = None
    priceBookId: str | None = None
    xref: list[dict[str, str]] | None = None
    productType: ProductType | None = None


def derive_sell(product: dict[str, Any]) -> float | None:
    """Sell follows the division's margin divisor unless a price is set explicitly."""
    if product.get("sellAt") is not None:
        return product["sellAt"]
    if product.get("cost") is None:
        return None
    priced = pricing.price_line(
        cost=product["cost"], margin=None, qty=1, division=product.get("division")
    )
    return priced["sell"]


def coerce_book_id(changes: dict[str, Any]) -> dict[str, Any]:
    """Store priceBookId as an ObjectId - the price-book routes query it as one."""
    if changes.get("priceBookId"):
        changes["priceBookId"] = oid(changes["priceBookId"])
    return changes
