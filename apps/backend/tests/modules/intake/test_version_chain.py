"""An estimate version is a link in a chain, and a sealed one stays sealed.

`collections.mongodb.md` §3.26 describes `estimateVersions` as an immutable chain
- v1 -> v2 -> v3 - where a superseded version records what replaced it and a
locked one "must never be written again".

What was stored instead was a bag of independent documents: no
`previousVersionId`, no `supersededByVersionId`, no `lockedAt`, no `status` and
no `statusHistory`. The head of the chain was whatever sorted highest by
`version`, nothing marked a version superseded, and `mark_reconciled` wrote to
versions that had already been created - including old ones.

FR-14 is the requirement underneath: absorb an addendum "without losing prior
work". A chain you cannot walk backwards is not prior work, it is a pile.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cbc.modules.intake.domain import versioning


def test_the_first_version_starts_a_chain() -> None:
    first = versioning.new_version(previous=None, number=1, reason="initial", actor="kevin")
    assert first["version"] == 1
    assert first["previousVersionId"] is None
    assert first["supersededByVersionId"] is None
    assert first["lockedAt"] is None
    assert first["status"] == "draft"
    assert first["statusHistory"] == []


def test_a_later_version_points_back(unlocked) -> None:
    second = versioning.new_version(previous=unlocked, number=2, reason="addendum", actor="kevin")
    assert second["previousVersionId"] == unlocked["_id"]
    assert second["version"] == 2


def test_superseding_seals_the_previous_version(unlocked) -> None:
    at = datetime(2026, 9, 6, tzinfo=timezone.utc)
    closed = versioning.supersede(unlocked, by_id="v2", at=at, actor="kevin")

    assert closed["supersededByVersionId"] == "v2"
    assert closed["lockedAt"] == at
    assert closed["status"] == "superseded"


def test_a_locked_version_refuses_further_writes(unlocked) -> None:
    """§3.26: a version with lockedAt set must never be written again."""
    sealed = {**unlocked, **versioning.supersede(unlocked, by_id="v2", actor="kevin")}

    with pytest.raises(versioning.VersionLocked) as raised:
        versioning.guard_writable(sealed)
    assert "superseded" in str(raised.value)


def test_an_open_version_accepts_writes(unlocked) -> None:
    versioning.guard_writable(unlocked)  # does not raise


def test_a_transition_is_recorded_with_who_and_why() -> None:
    entry = versioning.transition("draft", "priced", actor="kevin", note="pricing pass done")
    assert entry["from"] == "draft"
    assert entry["to"] == "priced"
    assert entry["by"] == "kevin"
    assert entry["note"] == "pricing pass done"
    assert entry["at"] is not None


def test_the_status_machine_refuses_a_transition_that_is_not_on_the_map() -> None:
    """Six states, and the edges between them are the specification's, not ours."""
    with pytest.raises(ValueError, match="draft -> sent"):
        versioning.transition("draft", "sent", actor="kevin")


def test_every_state_the_specification_names_is_reachable() -> None:
    reachable = {"draft"}
    frontier = ["draft"]
    while frontier:
        for nxt in versioning.TRANSITIONS.get(frontier.pop(), ()):
            if nxt not in reachable:
                reachable.add(nxt)
                frontier.append(nxt)
    assert reachable == set(versioning.STATUSES)


def test_approval_is_a_transition_a_person_makes() -> None:
    """NFR-1. Nothing reaches `approved` without an actor."""
    with pytest.raises(ValueError, match="approved"):
        versioning.transition("pendingReview", "approved", actor=None)


@pytest.fixture()
def unlocked() -> dict:
    return {
        "_id": "v1",
        "version": 1,
        "status": "draft",
        "lockedAt": None,
        "supersededByVersionId": None,
        "statusHistory": [],
    }
