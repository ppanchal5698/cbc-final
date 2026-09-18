"""P21 connector contract tests."""
from __future__ import annotations

import pytest
from _runtime import load_server

_server = load_server("p21-connector")
check_freshness = _server.check_freshness
lookup_last_po = _server.lookup_last_po
search_item = _server.search_item


@pytest.fixture(autouse=True)
def _clear_freshness_cache():
    """API settings tests share a process-wide bands cache with load_sync()."""
    from cbc.modules.ops.api import freshness as freshness_settings

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


def test_a_recent_purchase_order_price_is_usable() -> None:
    """Matrix 6.2: fresh up to ~6-8 months."""
    from datetime import date, timedelta

    recent = (date.today() - timedelta(days=30)).isoformat()
    result = check_freshness(recent)
    assert result["freshness_status"] == "fresh"
    assert result["usable"] is True
    assert check_freshness(
        (date.today() - timedelta(days=150)).isoformat()
    )["freshness_status"] == "fresh"


def test_a_price_past_the_review_window_is_unreliable() -> None:
    """A year-old cost used to come back `fresh` and go straight onto a quote."""
    from datetime import date, timedelta

    mid = (date.today() - timedelta(days=365)).isoformat()
    result = check_freshness(mid)
    assert result["freshness_status"] == "unreliable"
    assert result["usable"] is False


def test_a_price_older_than_the_discard_window_is_stale() -> None:
    """Matrix 6.2: 3-4 years must be discarded."""
    from datetime import date, timedelta

    old = (date.today() - timedelta(days=1200)).isoformat()
    result = check_freshness(old)
    assert result["freshness_status"] == "stale"
    assert result["usable"] is False


def test_lookup_with_base_url_uses_fresh_po(monkeypatch) -> None:
    """When P21_BASE_URL is set, a fresh last-PO becomes cost_source P21_LAST_PO."""
    from datetime import date, timedelta

    monkeypatch.setattr(_server, "BASE_URL", "https://p21.example.test")

    def fake_lookup(part_number, vendor=None):
        return {
            "last_po_price": 12.34,
            "po_date": (date.today() - timedelta(days=20)).isoformat(),
            "item_id": "ITEM-1",
        }

    monkeypatch.setattr(_server, "_http_lookup", fake_lookup)
    result = lookup_last_po("BB1279", vendor="Hager")
    assert result["connected"] is True
    assert result["cost_source"] == "P21_LAST_PO"
    assert result["last_po_price"] == 12.34
    assert result["freshness_status"] == "fresh"
    assert result.get("action_required") is None


def test_lookup_with_base_url_stale_po_requires_manual(monkeypatch) -> None:
    from datetime import date, timedelta

    monkeypatch.setattr(_server, "BASE_URL", "https://p21.example.test")

    def fake_lookup(part_number, vendor=None):
        return {
            "last_po_price": 9.99,
            "po_date": (date.today() - timedelta(days=1500)).isoformat(),
            "item_id": "ITEM-OLD",
        }

    monkeypatch.setattr(_server, "_http_lookup", fake_lookup)
    result = lookup_last_po("BB1279", vendor="Hager")
    assert result["cost_source"] == "P21_LAST_PO"
    assert result["freshness_status"] == "stale"
    assert result["action_required"] == "manual_price_entry"


def test_freshness_respects_a_narrower_admin_window(monkeypatch) -> None:
    from datetime import date, timedelta

    from cbc.modules.ops.api import freshness_rules as core
    from cbc.modules.ops.api.freshness import Bands

    bands = Bands(
        catalog_stale_months=6,
        discard_after_months=12,
        catalog_stale_days=core.days_from_months(6),
        discard_after_days=core.days_from_months(12),
        rule=core.rule_text(6, 12),
    )
    monkeypatch.setattr(_server, "load_sync", lambda: bands)
    mid = (date.today() - timedelta(days=250)).isoformat()
    result = check_freshness(mid)
    assert result["freshness_status"] == "unreliable"
    assert result["usable"] is False
    assert result["rule"] == bands.rule
