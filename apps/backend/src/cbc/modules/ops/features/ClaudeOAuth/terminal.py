"""Driving `claude setup-token` through a pseudo-terminal: what to look for, and reading it.

Every pattern here comes from bytes the real CLI emitted; tests/modules/ops/features/ClaudeOAuth_test.py
pins them against those captures.
"""
from __future__ import annotations

import os
import re
import time


# The CLI writes to a terminal, so the URL arrives wrapped in an OSC-8 hyperlink
# escape and terminated by BEL rather than by whitespace. Matching on \S+ swallows
# the escape; matching on the host alone misses it, because the authorization
# host is claude.com and not the claude.ai you would expect.
URL_PATTERN = re.compile("https://[^\\s\\x07\\x1b]+oauth/authorize[^\\s\\x07\\x1b]*")


# `claude setup-token` prints an sk-ant-oat… token on success.
_TOKEN_PATTERN = re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}")


# What ends the wait, either way. Without the failure half, a rejected code
# would block for the full timeout before reporting anything.
_OAUTH_ERROR = re.compile("OAuth error:[^\\r\\n]*|Request failed with status code [0-9]+")


_DONE_PATTERN = re.compile(_TOKEN_PATTERN.pattern + "|" + _OAUTH_ERROR.pattern)


# The prompt as it reads once the escapes are stripped - the CLI writes it
# with cursor moves between the words, so the spaces do not survive.
_PROMPT_PATTERN = re.compile("[Pp]aste ?code ?here")


# Cursor moves, colours and hyperlink wrappers, so an error can be read by a human.
_ANSI = re.compile("\\x1b\\[[0-9;?]*[A-Za-z]|\\x1b][^\\x07\\x1b]*(?:\\x07|\\x1b\\\\)|\\x1b\\([AB]|[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f]")


def _clean(text: str) -> str:
    return _ANSI.sub("", text)


def _read_until(fd: int, pattern: re.Pattern[str], timeout: int) -> str:
    """Drain a pty until the pattern shows up, the process ends, or time runs out."""
    import select

    deadline = time.time() + timeout
    buffered = ""
    while time.time() < deadline:
        readable, _, _ = select.select([fd], [], [], 1.0)
        if not readable:
            continue
        try:
            chunk = os.read(fd, 4096)
        except OSError:  # the child exited and closed its end
            break
        if not chunk:
            break
        buffered += chunk.decode("utf-8", errors="replace")
        # Against both the raw stream and the stripped one. The CLI positions the
        # cursor between words, so "Paste code here" arrives as
        # "Paste\x1b[8Gcode\x1b[13Ghere" and only matches once the escapes are
        # gone - a raw-only test silently waits out the whole timeout instead.
        if pattern.search(buffered) or pattern.search(_clean(buffered)):
            break
    return buffered
