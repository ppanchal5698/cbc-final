#!/usr/bin/env python3
"""PreToolUse guardrail: block anything that could send a quotation (NFR-1).

Exit 2 = block the tool call. Exit 0 = allow.
Rule: .claude/rules/human-in-the-loop.md
"""
from __future__ import annotations

import json
import re
import sys

MAIL_COMMAND = re.compile(
    r"\b(sendmail|mailx|mutt|msmtp|postfix|swaks)\b"
    # prefix match, so smtplib / smtpd / smtp-cli are caught too
    r"|\bsmtp"
    r"|\b(sendgrid|mailgun|postmark)"
    r"|curl[^|;&]*\bmail\b",
    re.IGNORECASE,
)
MAIL_TOOL = re.compile(r"send|email|mail", re.IGNORECASE)

BLOCK_MSG = (
    "BLOCKED: Sending quotations requires explicit estimator approval (NFR-1).\n"
    "The copilot drafts, sources, and calculates - it does not send.\n"
    "Write the draft to projects/{project}/ and halt with "
    '"Draft ready for estimator review".'
)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    return check(payload)


def check(payload: dict) -> int:
    tool_name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}
    command = str(tool_input.get("command") or "")

    if MAIL_COMMAND.search(command):
        print(BLOCK_MSG, file=sys.stderr)
        return 2

    # Guard MCP/tool names, but never the Read/Write/Edit family that legitimately
    # touches a file called quotation_email.md.
    if MAIL_TOOL.search(tool_name) and tool_name not in {"Read", "Write", "Edit", "Glob", "Grep"}:
        print(BLOCK_MSG, file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
