"""What indexing a price book may ask a model - only the table pages the reader
could not parse (the plan's `read_price_row`).

The model transcribes; code does every piece of arithmetic. Each row it reads
is marked as the model's, so a line priced from it says so and the estimator
confirms it against the sheet.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from cbc.shared import ai


class PriceRow(BaseModel):
    model: str = Field(min_length=1, max_length=60, description="The part or model number exactly as printed.")
    size: str | None = Field(default=None, max_length=60, description="The size printed for the row, if any.")
    finish: str | None = Field(default=None, max_length=30, description="The finish code exactly as printed: US26D, 626, ALM.")
    description: str | None = Field(default=None, max_length=200)
    list_price: float = Field(gt=0, description="The list price in dollars as printed, without $ or commas.")


class PriceTable(BaseModel):
    section: str | None = Field(default=None, max_length=120, description="The table's heading as printed.")
    rows: list[PriceRow]


READ_PRICE_TABLE = ai.Question(
    name="read_price_table",
    version=1,
    instructions=(
        "Transcribe the vendor price-book table in the image for an estimator: one row per "
        "list price, each with the part or model number it belongs to, the size and finish "
        "printed beside it, and the price exactly as printed. A value the page does not give "
        "is null. Never compute, round or infer a price, and never fill a row from another "
        "row or from what such tables usually hold. A page with no price table has no rows."
    ),
    answer=PriceTable,
)
