"""Domain ownership of job types - re-export migrated services.domains."""
from __future__ import annotations

from cbc.services.domains import DOMAIN_JOB_TYPES, claimable_types

__all__ = ["DOMAIN_JOB_TYPES", "claimable_types"]
