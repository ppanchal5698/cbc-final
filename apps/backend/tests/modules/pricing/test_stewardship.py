"""Who keeps each data set current, and when it is due (NFR-10, requirements 6.3)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cbc.modules.pricing.api import reference_store, stewardship


def test_a_set_is_due_until_reviewed_and_again_once_its_cadence_runs_out() -> None:
    reference_store.use_memory({})
    try:
        before = {row["family"]: row for row in stewardship.overview()}
        assert before["vendor_tiers"]["due"] is True, "never reviewed in the app"
        assert before["vendor_tiers"]["owner"] == "Purchasing"
        assert before["tax"]["due"] is False, "tax changes on an event, not a calendar"

        reference_store.put_family_sync("vendor_tiers", {"vendors": []}, actor="purchasing@cbc.example")
        now = datetime.now(timezone.utc)
        after = {row["family"]: row for row in stewardship.overview(now)}
        tiers = after["vendor_tiers"]
        assert (tiers["due"], tiers["updatedBy"]) == (False, "purchasing@cbc.example")
        assert timedelta(days=88) < tiers["reviewDue"] - now < timedelta(days=93)  # quarterly

        later = {row["family"]: row for row in stewardship.overview(now + timedelta(days=120))}
        assert later["vendor_tiers"]["due"] is True
    finally:
        reference_store.use_memory(None)
