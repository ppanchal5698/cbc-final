"""The questions pricing may ask a model, and the shape of their answers.

choose_catalog_match is asked only when the matcher has narrowed a specified item
to rows of one model that differ in price, and the legend's own words do not say
which. The model picks among those rows or says none; it never adds a part, and
the line it prices carries its reason and a flag for the estimator to confirm.

classify_supply is asked only when an item's words name another party without
saying who supplies it. An answer that someone else does moves the line out of
the base bid, flagged for the estimator to confirm; any other leaves it where
the code put it.
"""
from __future__ import annotations

from typing import Literal

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


class SupplyReading(BaseModel):
    supplier: Literal["CFCI", "OFCI", "BY_OTHERS", "UNCLEAR"] = Field(
        description="CFCI: CBC supplies it. OFCI: the owner or tenant does. BY_OTHERS: another "
                    "contractor or trade does. UNCLEAR: the words do not say.")
    reason: str = Field(max_length=300, description="The words that decide it.")


CLASSIFY_SUPPLY = ai.Question(
    name="classify_supply",
    version=1,
    instructions=(
        "CBC supplies door hardware and Division 10 specialties to the contractor on this "
        "bid. You read one item's words from an architect's schedule and say who supplies "
        "the item itself - never who installs, wires, powers, keys or selects it. A note "
        "that the electrician wires a power supply does not mean the electrician supplies "
        "it. Answer UNCLEAR when the words do not say: a wrong answer moves an item in or "
        "out of the bid, and an estimator will decide. Give the words that decide it."
    ),
    answer=SupplyReading,
)
