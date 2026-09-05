"""Schemas for editable reference-library data (pricing configuration)."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class MarginFrameworkUpdate(BaseModel):
    """Edit the product-type margin bands. Margins are fractions in [0, 1).

    `bands` maps a band key (e.g. "commodity") to its margin fraction. `accessories`
    edits the derived restroom-accessories rate. Both are optional so a caller can
    change one band without restating the rest.
    """

    bands: dict[str, float] | None = None
    accessories: float | None = Field(default=None, ge=0, lt=1)

    @field_validator("bands")
    @classmethod
    def _bands_in_range(cls, value: dict[str, float] | None) -> dict[str, float] | None:
        if value:
            for key, margin in value.items():
                if not 0 <= margin < 1:
                    raise ValueError(f"margin for {key!r} must be in [0, 1), got {margin}")
        return value


class TaxRatesUpdate(BaseModel):
    """Edit nexus sales-tax rates. Rates are fractions in [0, 1).

    `rates` upserts a jurisdiction -> rate mapping (two-letter state code). `remove`
    drops jurisdictions where CBC no longer has nexus; a dropped state then resolves
    to a 0% rate, like any state absent from the table.
    """

    rates: dict[str, float] | None = None
    remove: list[str] | None = None

    @field_validator("rates")
    @classmethod
    def _rates_in_range(cls, value: dict[str, float] | None) -> dict[str, float] | None:
        if value:
            for code, rate in value.items():
                if not 0 <= rate < 1:
                    raise ValueError(f"tax rate for {code!r} must be in [0, 1), got {rate}")
        return value


class HagerAddersUpdate(BaseModel):
    """Edit Hager list adders. Values are LIST dollar amounts (not fractions).

    `items` upserts a name -> dollar amount mapping; `remove` drops adders by name.
    """

    items: dict[str, float] | None = None
    remove: list[str] | None = None

    @field_validator("items")
    @classmethod
    def _non_negative(cls, value: dict[str, float] | None) -> dict[str, float] | None:
        if value:
            for name, amount in value.items():
                if amount < 0:
                    raise ValueError(f"adder {name!r} must not be negative, got {amount}")
        return value


class SpecialCustomerMargin(BaseModel):
    """One special-customer margin. `margin` may be null to leave it PENDING."""

    name: str = Field(min_length=1)
    margin: float | None = None
    note: str | None = None

    @field_validator("margin")
    @classmethod
    def _fraction(cls, value: float | None) -> float | None:
        if value is not None and not 0 <= value < 1:
            raise ValueError(f"margin must be in [0, 1), got {value}")
        return value


class SpecialMarginsUpdate(BaseModel):
    """Edit special-customer margins. `customers` upserts by name; `remove` drops by name."""

    customers: list[SpecialCustomerMargin] | None = None
    remove: list[str] | None = None


class FinishEntry(BaseModel):
    """One finish-crosswalk row. Keyed by us_code; other fields update in place."""

    us_code: str = Field(min_length=1)
    numeric_code: str | None = None
    description: str | None = None
    premium: bool | None = None
    note: str | None = None


class FinishesUpdate(BaseModel):
    """Edit the finish crosswalk. `finishes` upserts by us_code; `remove` drops by us_code."""

    finishes: list[FinishEntry] | None = None
    remove: list[str] | None = None


class WallTypeEntry(BaseModel):
    """One frame-depth row. `depth` is a label like '5-3/4'; inches are derived from it."""

    type: str = Field(min_length=1)
    depth: str | None = None
    note: str | None = None


class FrameDepthsUpdate(BaseModel):
    """Edit frame depths. `wall_types` upserts by type; `remove` drops by type."""

    wall_types: list[WallTypeEntry] | None = None
    remove: list[str] | None = None


class FrpConstantsUpdate(BaseModel):
    """Set FRP conversion constants (Open Item 5). Numeric fields must be >= 0.

    All fields are optional so one constant can be entered at a time; a field sent
    as null is cleared, which returns the table to PENDING.
    """

    panel_size: str | None = None
    waste_pct: float | None = None
    trim_stick_length: float | None = None
    adhesive_coverage_sqft_per_unit: float | None = None
    opening_handling: str | None = None

    @field_validator("waste_pct", "trim_stick_length", "adhesive_coverage_sqft_per_unit")
    @classmethod
    def _non_negative(cls, value: float | None) -> float | None:
        if value is not None and value < 0:
            raise ValueError(f"must not be negative, got {value}")
        return value


class VendorCategoriesUpdate(BaseModel):
    """PATCH category multipliers for one vendor in vendor_tiers."""

    vendor: str = Field(min_length=1)
    categories: dict[str, float]

    @field_validator("categories")
    @classmethod
    def _non_negative(cls, value: dict[str, float]) -> dict[str, float]:
        for key, amount in value.items():
            if amount < 0:
                raise ValueError(f"multiplier for {key!r} must not be negative")
        return value


class SpecialNetItem(BaseModel):
    part_number: str = Field(min_length=1)
    net_price: float | None = None
    item_code: str | None = None
    description: str | None = None
    section: str | None = None
    source_page: int | None = None

    @field_validator("net_price")
    @classmethod
    def _non_negative(cls, value: float | None) -> float | None:
        if value is not None and value < 0:
            raise ValueError(f"net_price must not be negative, got {value}")
        return value


class SpecialNetsUpdate(BaseModel):
    items: list[SpecialNetItem] | None = None
    remove: list[str] | None = None


class StockItem(BaseModel):
    part_number: str = Field(min_length=1)
    description: str | None = None
    note: str | None = None


class StockUpdate(BaseModel):
    items: list[StockItem] | None = None
    remove: list[str] | None = None


class LiteKitReplace(BaseModel):
    """Full document replace for lite_kit_prices."""

    data: dict


class CustomOtherMatrixReplace(BaseModel):
    data: dict
