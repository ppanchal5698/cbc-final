"""P21 connector contract tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "mcp-servers" / "p21-connector"))

from server import check_freshness, lookup_last_po, search_item  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_freshness_cache():
    """API settings tests share a process-wide bands cache with load_sync()."""
    from cbc.services import freshness as freshness_settings

    freshness_settings.clear_cache()
    yield
    freshness_settings.clear_cache()


def test_lookup_without_base_url_returns_manual_entry() -> None:
    result = lookup_last_po("BB1279", vendor="Hager")
    assert result["cost_source"] == "MANUAL"
    assert result["last_po_price"] is None


def test_search_without_base_url_is_empty() -> None:
    result = search_item("hinge")
    assert result["results"] == []
    assert result["connected"] is False


def test_freshness_under_twenty_four_months_is_usable() -> None:
    from datetime import date, timedelta

    recent = (date.today() - timedelta(days=30)).isoformat()
    result = check_freshness(recent)
    assert result["freshness_status"] == "fresh"
    assert result["usable"] is True
    still_fresh = (date.today() - timedelta(days=700)).isoformat()
    assert check_freshness(still_fresh)["freshness_status"] == "fresh"


def test_freshness_past_twenty_four_months_is_unreliable() -> None:
    from datetime import date, timedelta

    mid = (date.today() - timedelta(days=800)).isoformat()
    result = check_freshness(mid)
    assert result["freshness_status"] == "unreliable"
    assert result["usable"] is False


def test_freshness_over_two_and_a_half_years_is_stale() -> None:
    from datetime import date, timedelta

    old = (date.today() - timedelta(days=1000)).isoformat()
    result = check_freshness(old)
    assert result["freshness_status"] == "stale"
    assert result["usable"] is False


def test_freshness_respects_a_narrower_admin_window(monkeypatch) -> None:
    from datetime import date, timedelta

    from cbc.core import freshness as core
    from cbc.services.freshness import Bands
    import server as p21

    bands = Bands(
        catalog_stale_months=6,
        discard_after_months=12,
        catalog_stale_days=core.days_from_months(6),
        discard_after_days=core.days_from_months(12),
        rule=core.rule_text(6, 12),
    )
    monkeypatch.setattr(p21, "load_sync", lambda: bands)
    mid = (date.today() - timedelta(days=250)).isoformat()
    result = check_freshness(mid)
    assert result["freshness_status"] == "unreliable"
    assert result["usable"] is False
    assert result["rule"] == bands.rule
