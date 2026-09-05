#!/usr/bin/env python3
"""Single PreToolUse process: send-quote guard, then delete/write guard.

Exit 2 = block the tool call. Exit 0 = allow.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parent
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

import pre_delete_guard  # noqa: E402
import pre_send_quote  # noqa: E402


def check(payload: dict) -> int:
    blocked = pre_send_quote.check(payload)
    if blocked:
        return blocked
    return pre_delete_guard.check(payload)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    return check(payload)


if __name__ == "__main__":
    sys.exit(main())
