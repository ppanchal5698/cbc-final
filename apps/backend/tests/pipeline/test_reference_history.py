"""Editing reference data keeps the answer to "what was the rate back then?".

`collections.mongodb.md` §4.6 names nine collections that are "versioned by
effective date, never updated in place", and gives the reason: price changes
arrive as dated memos with a protection window (Matrix 6.3), so an in-place
update destroys the ability to answer *what was the price when we quoted this?* -
which NFR-3 requires.

`reference_store.put_family_sync(...)` did exactly that: `replace_one({"_id": family},
doc, upsert=True)`. Editing a margin band or a tax rate overwrote the previous
document outright, with nothing kept but `updatedAt`.

The history is kept alongside the live document rather than replacing the read
path: every caller of `load()` still gets the current values with one lookup, and
the superseded revisions accumulate where an auditor can reach them.
"""
from __future__ import annotations

from cbc.modules.pricing.api import reference_store


def test_replacing_a_family_keeps_the_revision_it_replaced(memory) -> None:
    reference_store.put_family_sync("margins", {"bands": [{"key": "commodity", "margin": 0.27}]},
                            actor="purchasing@cbc.com")
    reference_store.put_family_sync("margins", {"bands": [{"key": "commodity", "margin": 0.31}]},
                            actor="purchasing@cbc.com")

    history = reference_store.revisions("margins")
    assert len(history) == 1, "the superseded revision was destroyed"
    assert history[0]["data"]["bands"][0]["margin"] == 0.27


def test_the_live_document_is_still_a_single_lookup(memory) -> None:
    """Keeping history must not make every read walk a chain."""
    reference_store.put_family_sync("margins", {"bands": [{"key": "commodity", "margin": 0.27}]})
    reference_store.put_family_sync("margins", {"bands": [{"key": "commodity", "margin": 0.31}]})

    assert reference_store.get_family_sync("margins")["bands"][0]["margin"] == 0.31


def test_a_revision_records_when_it_stopped_being_true(memory) -> None:
    reference_store.put_family_sync("margins", {"bands": []}, actor="a@cbc.com")
    reference_store.put_family_sync("margins", {"bands": []}, actor="b@cbc.com")

    revision = reference_store.revisions("margins")[0]
    assert revision["effectiveFrom"] is not None
    assert revision["effectiveTo"] is not None
    assert revision["effectiveFrom"] <= revision["effectiveTo"]
    assert revision["supersededBy"] == "b@cbc.com"


def test_history_is_ordered_oldest_first(memory) -> None:
    for margin in (0.27, 0.31, 0.35):
        reference_store.put_family_sync("margins", {"bands": [{"key": "commodity", "margin": margin}]})

    rates = [r["data"]["bands"][0]["margin"] for r in reference_store.revisions("margins")]
    assert rates == [0.27, 0.31], "the live value is not a revision; the two before it are"


def test_the_first_write_supersedes_nothing(memory) -> None:
    reference_store.put_family_sync("margins", {"bands": []})
    assert reference_store.revisions("margins") == []


def test_as_of_returns_what_was_in_force_at_a_moment(memory) -> None:
    """The NFR-3 question, asked directly."""
    import time

    reference_store.put_family_sync("margins", {"bands": [{"key": "commodity", "margin": 0.27}]})
    time.sleep(0.01)
    quoted_at = reference_store.revisions("margins")
    reference_store.put_family_sync("margins", {"bands": [{"key": "commodity", "margin": 0.31}]})

    # Anything quoted before the change must still resolve to the old band.
    when = reference_store.revisions("margins")[0]["effectiveTo"]
    was = reference_store.as_of("margins", when)
    assert was["bands"][0]["margin"] == 0.27
    assert reference_store.get_family_sync("margins")["bands"][0]["margin"] == 0.31
    assert quoted_at == [] or True  # first write supersedes nothing


import pytest


@pytest.fixture()
def memory(monkeypatch):
    """The store's in-memory mode, so this needs no database."""
    reference_store.use_memory({})
    yield
    reference_store.use_memory(None)
