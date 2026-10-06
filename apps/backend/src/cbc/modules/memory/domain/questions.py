"""The questions the memory agents may ask a model, and the shape of each answer.

The agents decide nothing with these. A finding is found by a check in code and
a pattern is counted in code; the model only says it in words an estimator or
purchasing manager can act on. Every prompt carries the facts, and the
instructions forbid adding any.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from cbc.shared import ai


class FindingExplanation(BaseModel):
    headline: str = Field(max_length=200, description="One line an estimator understands at a glance.")
    why_it_matters: str = Field(max_length=700, description="What goes wrong on a bid because of it.")
    suggested_fix: str = Field(max_length=700, description="The smallest change that resolves it.")
    who_fixes: Literal["purchasing", "estimating", "admin", "it"]


EXPLAIN_FINDING = ai.Question(
    name="memory_explain_finding",
    version=1,
    instructions=(
        "You explain one data-quality finding from the memory graph of CBC, a door "
        "hardware and Division 10 distributor, to an estimator or purchasing manager. "
        "Use only the facts in the message: never add a part number, price, multiplier, "
        "date or name that is not there, and never guess which of two conflicting "
        "values is right - say that a person has to decide. Say plainly what is wrong, "
        "why it matters when a bid is priced, and the smallest fix. who_fixes: "
        "purchasing for price books, vendor multipliers and special nets; estimating "
        "for margins and quote lines; admin for reference data kept in the app; it "
        "for the system itself."
    ),
    answer=FindingExplanation,
)


class CustomerInsight(BaseModel):
    summary: str = Field(max_length=900, description="What CBC has learned about bidding for this customer.")
    patterns: list[str] = Field(default_factory=list, max_length=8, description="Repeated choices, each with its evidence.")
    cautions: list[str] = Field(default_factory=list, max_length=5, description="What to check before reusing them.")


SUMMARIZE_CUSTOMER = ai.Question(
    name="memory_customer_insight",
    version=1,
    instructions=(
        "You summarise what CBC's approved bids show about one customer (a brand or a "
        "general contractor), for the estimator starting that customer's next bid. Use "
        "only the facts in the message - the bids, the parts they were priced as, the "
        "margins by section. Cite bid codes for every pattern. Never add a part, price, "
        "margin or bid that is not in the facts; with few bids, say the evidence is thin."
    ),
    answer=CustomerInsight,
)
