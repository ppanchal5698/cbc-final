"""The cross-cutting document rules from `collections.mongodb.md` §4.2-§4.6.

None of these mechanisms existed before: `orgId`, `schemaVersion`, `isDeleted`
and `effectiveFrom` appeared nowhere in the repository. These tests fix the
shapes so the repositories that apply them have something to be right about.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cbc.shared.persistence import envelope, names


def test_a_new_document_carries_the_whole_envelope() -> None:
    stamped = envelope.stamp_new({"code": "CBC-260002"}, org_id="org1", actor_id="user1")
    assert stamped["orgId"] == "org1"
    assert stamped["schemaVersion"] == envelope.SCHEMA_VERSION
    assert stamped["createdBy"] == stamped["updatedBy"] == "user1"
    assert stamped["createdAt"] == stamped["updatedAt"], "one clock per document"
    assert stamped["code"] == "CBC-260002", "the caller's fields survive"


def test_stamping_does_not_mutate_the_caller() -> None:
    original = {"code": "CBC-260002"}
    envelope.stamp_new(original, org_id="org1")
    assert original == {"code": "CBC-260002"}


def test_a_system_write_has_no_actor() -> None:
    """Nullable by design - imports and background jobs have no user."""
    stamped = envelope.stamp_new({}, org_id="org1")
    assert stamped["createdBy"] is None and stamped["updatedBy"] is None


def test_an_update_never_touches_created_at() -> None:
    changes = envelope.stamp_update({"stage": "quote"}, actor_id="user2")
    assert set(changes) == {"stage", "updatedAt", "updatedBy"}
    assert "createdAt" not in changes and "createdBy" not in changes


# ── §4.3 soft delete ────────────────────────────────────────────────────────


def test_soft_delete_applies_to_five_collections_and_only_five() -> None:
    assert envelope.SOFT_DELETED == {
        names.ESTIMATES,
        names.ESTIMATE_VERSIONS,
        names.BID_REQUESTS,
        names.PRICE_BOOKS,
        "vendors",
    }
    for append_only in (names.AUDIT_LOGS, names.FEEDBACK_EVENTS):
        assert append_only not in envelope.SOFT_DELETED
    for child in (names.OPENINGS, names.ESTIMATE_LINES, names.TAKEOFFS):
        assert child not in envelope.SOFT_DELETED, "hidden by the parent, not itself"


def test_retention_policy_is_not_invented() -> None:
    """The workbook gives no retention rule; §4.3 says not to manufacture one."""
    assert "retentionPolicy" not in envelope.soft_delete()


def test_the_alive_filter_sees_documents_written_before_the_field_existed() -> None:
    """`isDeleted: False` would hide every pre-backfill document."""
    assert envelope.alive() == {"isDeleted": {"$ne": True}}


# ── §4.6 effective dating ───────────────────────────────────────────────────


def test_effective_dating_covers_the_nine_reference_collections() -> None:
    assert names.PRICE_BOOKS in envelope.EFFECTIVE_DATED
    assert "marginRules" in envelope.EFFECTIVE_DATED
    assert "taxRules" in envelope.EFFECTIVE_DATED
    assert len(envelope.EFFECTIVE_DATED) == 9


def test_a_record_in_force_has_no_end_date() -> None:
    start = datetime(2026, 2, 2, tzinfo=timezone.utc)
    row = envelope.effective({"multiplier": 0.29}, frm=start)
    assert row["effectiveFrom"] == start
    assert row["effectiveTo"] is None


def test_in_force_at_asks_the_question_nfr3_needs() -> None:
    """What was the rate when we quoted this?"""
    when = datetime(2026, 6, 1, tzinfo=timezone.utc)
    query = envelope.in_force_at(when)
    assert query["effectiveFrom"] == {"$lte": when}
    assert {"effectiveTo": None} in query["$or"]
    assert {"effectiveTo": {"$gt": when}} in query["$or"]


def test_superseding_closes_a_record_rather_than_replacing_it() -> None:
    """`reference_store.replace_one` destroyed the previous document outright."""
    at = datetime(2026, 3, 1, tzinfo=timezone.utc)
    assert envelope.supersede(at=at) == {"effectiveTo": at}


def test_a_history_reads_as_two_rows_not_one_edit() -> None:
    """The shape a price change has to leave behind."""
    first = datetime(2026, 2, 2, tzinfo=timezone.utc)
    second = first + timedelta(days=90)

    old = envelope.effective({"multiplier": 0.29}, frm=first)
    old.update(envelope.supersede(at=second))
    new = envelope.effective({"multiplier": 0.31}, frm=second)

    quoted_at = first + timedelta(days=10)
    assert old["effectiveFrom"] <= quoted_at < old["effectiveTo"]
    assert new["effectiveFrom"] > quoted_at
    assert new["effectiveTo"] is None
