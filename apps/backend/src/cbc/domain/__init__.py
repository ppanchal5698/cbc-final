"""The rules of the estimating business, with nothing else attached.

A module belongs here when it can be reasoned about on paper: door-size notation,
the margin divisor, how old a purchase-order price may be, what a finish code
means in the other nomenclature. No Mongo, no FastAPI, no filesystem, no clock -
give it the facts and it returns an answer.

That constraint is the point. These are the rules an estimator would recognise,
and CBC's own accuracy rules (`.claude/rules/accuracy-trust.md`) turn on getting
them exactly right, so they need to be readable and testable without a database
in the room. `tests/api/test_layering.py` enforces the direction: everything may
import `cbc.domain`, and `cbc.domain` imports nothing above it.

Live values that a person can edit - margin bands, tax rates, freshness windows -
are looked up by the modules and *passed in*. The rule never fetches its own
inputs.
"""
