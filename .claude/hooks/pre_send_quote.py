#!/usr/bin/env python3
"""PreToolUse guardrail: block anything that could send a quotation (NFR-1).

Exit 2 = block the tool call. Exit 0 = allow.
Rule: .claude/rules/00-core-constraints.md

Commands are read through `_shell`, so what is checked is the program that would
run, not every word on the line. Searching the raw text missed PowerShell's
`Send-MailMessage`, `aws ses`, a mail API reached with `node -e "fetch(...)"`, and
blocked `grep -rn smtp_host config/` - a read - for containing the word.

This is a backstop. The control that does not depend on reading a command is an
agent environment with no mail or messaging credentials in it: see the patches
README.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _shell  # noqa: E402  (a sibling module; the hook runs as a script)

# Programs whose job is to send mail.
MAILERS = {
    "sendmail", "mailx", "mail", "nail", "s-nail", "mutt", "neomutt", "msmtp", "ssmtp",
    "esmtp", "postfix", "exim", "exim4", "swaks", "mailsend", "blat",
    "send-mailmessage", "send-mgusermail", "send-mgusermessage",
}
HTTP_CLIENTS = {"curl", "wget", "http", "https", "xh", "httpie", "invoke-webrequest",
                "invoke-restmethod", "iwr", "irm", "aria2c"}
# Hosts of mail and messaging APIs. A URL whose host or path names mail is caught
# without being listed here; these are the ones that do not.
SEND_HOSTS = (
    "sendgrid.com", "sendgrid.net", "postmarkapp.com", "resend.com", "sparkpost.com",
    "mailjet.com", "mandrillapp.com", "brevo.com", "sendinblue.com", "mailchimp.com",
    "mailersend.com", "smtp2go.com", "elasticemail.com", "hooks.slack.com",
    "discord.com", "webhook.office.com", "api.telegram.org", "chat.googleapis.com",
)
# Mail libraries and calls, in code a command runs inline.
MAIL_CODE = re.compile(
    r"\bsmtplib\b|\bSMTP(?:_SSL)?\s*\(|\bsendmail\s*\(|\.send_message\s*\(|nodemailer|"
    r"@sendgrid/|\bsendgrid\b|\bmailgun\b|\bpostmark|\bresend\b|\bsparkpost\b|\bmailjet\b|"
    r"Net::SMTP|MIME::Lite|Mail::Sender|\bmail\s*\(|send_raw_email|\bsend_?email\s*\(|"
    r"\bsendMail\b|\bclient\(\s*['\"]ses(?:v2)?['\"]",
    re.IGNORECASE,
)
MAIL_IMPORT = re.compile(
    r"^\s*(?:import|from)\s+(?:smtplib|sendgrid|mailgun|postmarker|postmark|resend|yagmail|"
    r"redmail|exchangelib|O365)\b|\bclient\(\s*['\"]ses(?:v2)?['\"]",
    re.MULTILINE,
)
URL_IN_CODE = re.compile(r"(?:https?|smtps?)://[^\s'\"`)]+", re.IGNORECASE)

# MCP tools that send, by name; and meta-tools that take the action as an argument.
MAIL_TOOL = re.compile(r"send|e?mail|reply|forward|post_?message|chat[._]?post", re.IGNORECASE)
META_TOOL = re.compile(r"execute|invoke|run_?action|call_?tool|perform", re.IGNORECASE)
SEND_ACTION = re.compile(
    r"(?:send|reply|forward)[_\- ]?(?:e?mail|message|msg)|e?mail[_\- ]?send|post[_\- ]?message",
    re.IGNORECASE,
)
_EXEMPT_TOOLS = {"Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "Glob", "Grep"}
_AWS_VALUE_OPTIONS = {"--region", "--profile", "--output", "--endpoint-url", "--query",
                      "--color", "--ca-bundle", "--cli-read-timeout", "--cli-connect-timeout"}

BLOCK_MSG = (
    "BLOCKED: Sending quotations requires explicit estimator approval (NFR-1).\n"
    "The copilot drafts, sources, and calculates - it does not send.\n"
    "Write the draft into the bid's project folder and halt with "
    '"Draft ready for estimator review".'
)


def _is_send_url(word: str) -> bool:
    """A URL that reaches a mail server, a mail API or a messaging webhook."""
    lowered = word.strip("'\"").lower()
    if lowered.startswith(("smtp://", "smtps://", "mailto:")):
        return True
    if "://" not in lowered:
        if not re.match(r"^[a-z0-9.-]+\.[a-z]{2,}(?:[:/]|$)", lowered):
            return False
        lowered = "https://" + lowered
    try:
        parts = urlsplit(lowered)
        host = parts.hostname or ""
    except ValueError:
        return False
    pieces = re.split(r"[./_\-]", host) + re.split(r"[/_\-.?=&]", parts.path)
    if any("mail" in piece or piece.startswith("smtp") for piece in pieces if piece):
        return True
    if any(host == h or host.endswith("." + h) for h in SEND_HOSTS):
        return True
    if host.endswith("amazonaws.com") and re.search(r"(?:^|\.)(?:email|ses|email-smtp)(?:\.|$)", host):
        return True
    return "/webhooks/" in parts.path or "/webhook/" in parts.path


def _aws_sends(words: list[str]) -> bool:
    rest, index = [], 1
    while index < len(words):
        word = words[index]
        if word in _AWS_VALUE_OPTIONS:
            index += 2
            continue
        if not word.startswith("-"):
            rest.append(word)
        index += 1
    service, action = (rest + ["", ""])[:2]
    if service in ("ses", "sesv2", "pinpoint-email") and action.startswith("send"):
        return True
    return service == "sns" and action == "publish"


def _sends(command: str, cwd: str) -> str | None:
    """What in this command line would send, or None."""
    for simple in _shell.parse(command, cwd):
        words, name = simple.words, simple.name
        if name in MAILERS:
            return name
        if name == "aws" and _aws_sends(words):
            return "aws " + " ".join(w for w in words[1:3])
        if name == "az" and {"communication", "email", "send"} <= set(words):
            return "az communication email send"
        if name in HTTP_CLIENTS:
            if any(w.startswith("--mail-") for w in words):
                return f"{name} --mail-*"
            for word in words[1:]:
                if _is_send_url(word):
                    return f"{name} {word}"
        code = _shell.inline_code(simple)
        if code:
            if match := MAIL_CODE.search(code):
                return match.group(0)
            for url in URL_IN_CODE.findall(code):
                if _is_send_url(url):
                    return url
        script = _shell.script_path(simple)
        if script is not None:
            try:
                if script.is_file() and script.stat().st_size <= 1_000_000:
                    if match := MAIL_IMPORT.search(script.read_text(encoding="utf-8", errors="replace")):
                        return f"{script.name}: {match.group(0).strip()}"
            except OSError:
                pass
    return None


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _strings(item)]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    return []


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

    if command and _sends(command, str(payload.get("cwd") or os.getcwd())):
        print(BLOCK_MSG, file=sys.stderr)
        return 2

    # Guard MCP/tool names, but never the Read/Write/Edit family that legitimately
    # touches a file called quotation_email.md.
    if tool_name not in _EXEMPT_TOOLS:
        if MAIL_TOOL.search(tool_name):
            print(BLOCK_MSG, file=sys.stderr)
            return 2
        if META_TOOL.search(tool_name) and any(SEND_ACTION.search(s) for s in _strings(tool_input)):
            print(BLOCK_MSG, file=sys.stderr)
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
