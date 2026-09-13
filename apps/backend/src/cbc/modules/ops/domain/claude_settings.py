"""The Claude provider settings a request carries, and how a masked secret is recognised.

Shared by saving the settings and testing them, which must accept exactly the same
fields: a test that read a field saving ignored would test a configuration nobody
can store.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from cbc.services import provider  # ponytail: provider moves into ops with the worker (step 3.3d)


class ClaudeSettings(BaseModel):
    """Only the fields for the selected mode are read; the rest are ignored."""

    mode: str = Field(default=provider.SUBSCRIPTION)
    oauthToken: str | None = None
    apiKey: str | None = None
    authToken: str | None = None
    bedrockApiKey: str | None = None
    baseUrl: str | None = None
    awsRegion: str | None = None
    model: str | None = None
    smallFastModel: str | None = None


def is_masked(value: str) -> bool:
    """Is this the mask the settings screen was shown, rather than a new secret?

    The screen renders a credential as `sk-a********egAA`, and the form posts back
    whatever is in the box. Testing only for a string of asterisks never fired,
    because the mask keeps the first and last four characters - so Save wrote the
    mask over the real credential and Test authenticated with it. A real secret
    never contains a run of asterisks.
    """
    return "****" in value
