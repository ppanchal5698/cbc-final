#!/usr/bin/env python3
"""Single PostToolUse process: validate, then format, then audit.

Audit always runs. Scope-checkpoint validation may return exit 2 to block the
pipeline when scope_metadata / scope_summary is invalid mid-chain.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parent
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

import log_audit_trail  # noqa: E402
import post_extraction_validate  # noqa: E402
import post_quote_format  # noqa: E402


def check(payload: dict) -> int:
    # Audit first (NFR-3). Then validation may block on bad scope checkpoints.
    try:
        log_audit_trail.check(payload)
    except Exception as exc:  # noqa: BLE001
        print(f"hook log_audit_trail failed: {exc}", file=sys.stderr)

    block = 0
    try:
        block = int(post_extraction_validate.check(payload) or 0)
    except Exception as exc:  # noqa: BLE001
        print(f"hook post_extraction_validate failed: {exc}", file=sys.stderr)

    try:
        post_quote_format.check(payload)
    except Exception as exc:  # noqa: BLE001
        print(f"hook post_quote_format failed: {exc}", file=sys.stderr)

    return block


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    return check(payload)


if __name__ == "__main__":
    sys.exit(main())
