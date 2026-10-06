"""What the comparison harness (scripts/eval_bids.py) may ask of quoting.

A bid's priced take-off exactly as the v2 job prices it - the job's own code,
not a copy - without asking the model, so a run repeats, and written nowhere.
"""
from __future__ import annotations

from typing import Any


async def priced_take_off(project: dict[str, Any]) -> dict[str, Any]:
    from cbc.modules.quoting.features import MatchAndPrice

    return await MatchAndPrice.price_bid(project, choose=False)
