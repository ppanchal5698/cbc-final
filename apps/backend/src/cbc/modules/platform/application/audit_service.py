"""Re-export migrated audit service."""
from __future__ import annotations

from cbc.services import audit as _audit

record = _audit.record
