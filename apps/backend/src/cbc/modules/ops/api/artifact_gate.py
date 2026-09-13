"""The error that ends a pass's job at once: its output failed the contract.

Output that fails its contract fails the same way on every retry, so the Claude
pass finishes the job permanently (`artifact_validation`) instead of spending its
attempts. Extraction's artifact checks raise it and ops' Claude pass catches it;
it lives in ops' api so the catcher does not have to import the raiser.
"""
from __future__ import annotations

from typing import Any


class ArtifactValidationError(ValueError):
    """A job's artifacts failed the worker gate. Do not retry the whole run."""

    def __init__(
        self,
        message: str,
        *,
        phase: str | None = None,
        phase_state: dict[str, Any] | None = None,
        quarantine: list[dict[str, Any]] | None = None,
    ):
        super().__init__(message)
        self.phase = phase
        self.phase_state = phase_state or {}
        self.quarantine = quarantine or []
