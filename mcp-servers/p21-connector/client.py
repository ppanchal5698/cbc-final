"""Read-only HTTP client for Prophet 21 (NR-10).

Endpoint shape is configurable until CBC IT confirms the production contract.
Every failure path returns the MANUAL_ENTRY contract so pricing agents never see
a half-answer.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

BASE_URL = os.environ.get("P21_BASE_URL", "").strip().rstrip("/")
API_KEY = os.environ.get("P21_API_KEY", "").strip()
LOOKUP_PATH = os.environ.get("P21_LOOKUP_PATH", "/api/items/{part_number}/last-po")
SEARCH_PATH = os.environ.get("P21_SEARCH_PATH", "/api/items/search")
TIMEOUT = float(os.environ.get("P21_TIMEOUT_SECONDS", "15"))


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    return headers


def _request(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=_headers(), method="GET")
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        payload = response.read()
        if not payload:
            return {}
        return json.loads(payload.decode("utf-8"))


def lookup_last_po(part_number: str, vendor: str | None = None) -> dict[str, Any]:
    path = LOOKUP_PATH.format(part_number=urllib.parse.quote(part_number, safe=""))
    url = f"{BASE_URL}{path}"
    if vendor:
        url = f"{url}?{urllib.parse.urlencode({'vendor': vendor})}"
    return _request(url)


def search_item(query: str, limit: int = 10) -> dict[str, Any]:
    params = urllib.parse.urlencode({"q": query, "limit": str(limit)})
    url = f"{BASE_URL}{SEARCH_PATH}?{params}"
    return _request(url)
