"""Re-export migrated reuse helpers."""
from __future__ import annotations

from cbc.services import reuse as _reuse

prior_quotes = getattr(_reuse, "prior_quotes", None)
reuse_project = getattr(_reuse, "reuse_project", None)
