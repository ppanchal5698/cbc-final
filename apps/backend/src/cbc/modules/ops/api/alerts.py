"""Operator alerts for dead-lettered jobs.

Posts a Slack-compatible JSON body to ALERT_WEBHOOK_URL when set. Missing or
empty URL is a no-op so local compose does not depend on a chat connector.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger("cbc.alerts")


def webhook_url() -> str:
    return os.environ.get("ALERT_WEBHOOK_URL", "").strip()


def notify(text: str, *, extra: dict[str, Any] | None = None) -> bool:
    """Fire-and-forget webhook. Never raises. Returns True when a post succeeded."""
    url = webhook_url()
    if not url:
        return False
    payload: dict[str, Any] = {"text": text}
    if extra:
        payload.update(extra)
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.warning("alert webhook failed: %s", exc)
        return False
