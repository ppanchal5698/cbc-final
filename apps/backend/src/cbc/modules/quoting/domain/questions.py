"""The question pricing may ask a model, and the shape of its answer.

Asked only when the matcher has narrowed a specified item to rows of one model
that differ in price, and the legend's own words do not say which. The model
picks among those rows or says none; it never adds a part, and the line it
prices carries its reason and a flag for the estimator to confirm.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from cbc.shared import ai


class CatalogChoice(BaseModel):
    choice: int | None = Field(description="The number of the row the specified item is, or null when no row is it.")
    reason: str = Field(max_length=400, description="Which words of the specification decide it.")


CHOOSE_CATALOG_MATCH = ai.Question(
    name="choose_catalog_match",
    version=1,
    instructions=(
        "You match one specified door-hardware or Division 10 item from an architect's "
        "schedule to one row of a vendor price list, for CBC, a distributor. Every row "
        "offered is the same model; they differ by function, size, option or finish. "
        "Choose the row whose description the specification describes - its function "
        "(entry, storeroom, passage), arm, length, core or finish. If the specification "
        "does not say enough to tell them apart, answer null: a wrong row is a wrong "
        "price nobody sees, and an estimator will choose. Never answer with a row that "
        "is not listed. Give the words of the specification that decide it."
    ),
    answer=CatalogChoice,
)
