"""Operator webhook is a no-op without ALERT_WEBHOOK_URL."""
from __future__ import annotations

from cbc.services import alerts


def test_notify_is_silent_without_url(monkeypatch) -> None:
    monkeypatch.delenv("ALERT_WEBHOOK_URL", raising=False)
    assert alerts.notify("dead-letter") is False


def test_notify_posts_slack_json(monkeypatch) -> None:
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "http://example.test/hook")
    seen: dict = {}

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=5):
        seen["url"] = request.full_url
        seen["body"] = request.data
        return _Resp()

    monkeypatch.setattr(alerts.urllib.request, "urlopen", fake_urlopen)
    assert alerts.notify("hello", extra={"jobType": "extract_bid_set"}) is True
    assert seen["url"] == "http://example.test/hook"
    assert b"hello" in seen["body"]
    assert b"extract_bid_set" in seen["body"]
