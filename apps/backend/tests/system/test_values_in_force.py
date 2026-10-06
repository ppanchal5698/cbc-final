"""Every run's prompt carries the numbers no tool serves, read from their owners.

The confidence floor and the freshness windows were typed into agent and skill
text, where copies drift. They are rendered into the prompt from their owners
instead, and the orchestrator hands them on in every brief: a subagent sees only
its own definition and the brief, never the orchestrator's prompt.
"""
from __future__ import annotations

import dataclasses

import pytest

from cbc.modules.ops.api import freshness
from cbc.modules.pricing.api import confidence
from cbc.worker_kit import prompts

PROJECT = {"slug": "dutch_bros", "code": "DB-001"}
# Not ingest_pricebook: it reads a sheet into catalog rows and makes no
# confidence or freshness decision, and its prompt is built apart from a bid's.
JOB_TYPES = [t for t in prompts.TEMPLATES if t != "ingest_pricebook"]


def _owners(monkeypatch: pytest.MonkeyPatch, *, floor: float, fresh: int, stale: int) -> None:
    """Move the owners' values, so a prompt that hard-coded them would show the old ones."""
    monkeypatch.setattr(confidence, "CONFIDENCE_FLOOR", floor)
    bands = dataclasses.replace(
        freshness.DEFAULTS,
        fresh_months=fresh,
        catalog_stale_months=stale,
        rule=f"under ~{fresh} months fresh",
    )
    monkeypatch.setattr(freshness, "load_sync", lambda: bands)


@pytest.mark.parametrize("job_type", JOB_TYPES)
def test_every_job_prompt_carries_the_values_from_their_owners(job_type, monkeypatch) -> None:
    _owners(monkeypatch, floor=0.81, fresh=7, stale=19)
    text = prompts.build({"type": job_type, "payload": {}}, PROJECT)

    assert "**Values in force**" in text
    assert "Confidence floor: 0.81" in text
    assert "under ~7 months fresh" in text
    assert "review window: 19 months" in text


def test_every_wave_leg_carries_them(monkeypatch) -> None:
    _owners(monkeypatch, floor=0.81, fresh=7, stale=19)
    legs = prompts.build_wave(
        {"type": "extract_bid_set"}, {"code": "CBC-1", "slug": "demo"}, [("takeoff", [20]), ("frp", [14])]
    )
    for label, text in legs:
        assert "Confidence floor: 0.81" in text, label


def test_the_brief_template_hands_them_to_every_subagent() -> None:
    assert "Values in force" in prompts.DELEGATION_RULE
