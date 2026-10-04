"""Where `extracted/hardware_sets.json` keeps its sets - the one list every reader uses.

Three writers use three keys: the hardware-legend seed writes `sets`, the
product-matcher writes `groups`, and the normaliser was written for
`hardware_sets`. Each reader kept its own list and none had all three, so
pre-pricing read no sets from a matcher's file: a re-price after matching rebuilt
the priced file with zero lines, over the agent's patched MANUAL lines.
"""
from __future__ import annotations

SET_KEYS = ("hardware_sets", "sets", "groups")
