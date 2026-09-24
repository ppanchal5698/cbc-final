"""W4: the read-only Python P21 client and its per-pass cache."""
from __future__ import annotations

from datetime import date, timedelta

from cbc.modules.pricing.api import p21


def test_public_surface_is_last_po_only() -> None:
    assert p21.__all__ == ["last_po"]
    # A write verb added to this module fails the suite rather than the review.
    for name in dir(p21):
        assert not any(
            verb in name.lower() for verb in ("write", "update", "insert", "create", "delete", "post")
        ), name


def test_no_base_url_returns_none(monkeypatch) -> None:
    monkeypatch.delenv("P21_BASE_URL", raising=False)
    assert p21.last_po("010108", "Hager") is None


def test_a_fresh_po_is_priced(monkeypatch) -> None:
    monkeypatch.setenv("P21_BASE_URL", "http://p21.local")
    monkeypatch.setattr(
        p21, "_get", lambda url, **k: {"last_po_price": 42.0, "po_date": date.today().isoformat()}
    )
    result = p21.P21Client().last_po("X", "Hager")
    assert result is not None and result["cost"] == 42.0


def test_a_stale_po_is_written_nowhere(monkeypatch) -> None:
    monkeypatch.setenv("P21_BASE_URL", "http://p21.local")
    monkeypatch.setattr(p21, "_get", lambda url, **k: {"last_po_price": 42.0, "po_date": "2010-01-01"})
    assert p21.P21Client().last_po("X", "Hager") is None


def test_an_unreliable_po_is_context_not_cost(monkeypatch) -> None:
    monkeypatch.setenv("P21_BASE_URL", "http://p21.local")
    old = (date.today() - timedelta(days=300)).isoformat()  # >6mo, <3yr
    monkeypatch.setattr(p21, "_get", lambda url, **k: {"last_po_price": 42.0, "po_date": old})
    result = p21.P21Client().last_po("X", "Hager")
    assert result is not None and result.get("cost") is None
    assert "unreliable" in result.get("context", "")


def test_two_passes_do_not_share_a_price(monkeypatch) -> None:
    """Same part, two seed_line_items-style passes: each builds its own client, so
    a second pass sees the second PO price, not the first (leaked) one."""
    monkeypatch.setenv("P21_BASE_URL", "http://p21.local")
    prices = iter([10.0, 20.0])
    monkeypatch.setattr(
        p21,
        "_get",
        lambda url, **k: {"last_po_price": next(prices), "po_date": date.today().isoformat()},
    )
    first = p21.P21Client().last_po("SAME", "Hager")
    second = p21.P21Client().last_po("SAME", "Hager")
    assert first["cost"] == 10.0
    assert second["cost"] == 20.0


def test_one_client_caches_within_a_pass(monkeypatch) -> None:
    monkeypatch.setenv("P21_BASE_URL", "http://p21.local")
    prices = iter([10.0, 20.0])
    monkeypatch.setattr(
        p21,
        "_get",
        lambda url, **k: {"last_po_price": next(prices), "po_date": date.today().isoformat()},
    )
    client = p21.P21Client()
    assert client.last_po("SAME", "Hager")["cost"] == 10.0
    assert client.last_po("SAME", "Hager")["cost"] == 10.0  # cached, not 20.0


def test_the_breaker_stops_after_one_failure(monkeypatch) -> None:
    monkeypatch.setenv("P21_BASE_URL", "http://p21.local")
    calls = {"n": 0}

    def boom(url, **k):
        calls["n"] += 1
        raise OSError("p21 down")

    monkeypatch.setattr(p21, "_get", boom)
    client = p21.P21Client()
    assert client.last_po("A", "Hager") is None
    assert client.last_po("B", "Hager") is None
    assert calls["n"] == 1, "the breaker must not keep dialling a dead endpoint"
