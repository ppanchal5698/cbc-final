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

# What an intact reading starts with. A candidate missing it lost a character on
# the way out of the terminal; it was not issued wrongly.
_TOKEN_PREFIX = "sk-ant-oat"


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


# The same rules, minus the one that can delete a character of real text.
#
# `_ANSI`'s CSI branch is `ESC [ <params> <letter>` and the parameters are
# optional, so a bare `ESC [` in front of a letter takes that letter as its
# terminator and removes it with the escape. Not hypothetical: it turned
# sk-ant-oat01-... into sk-ant-at01-..., 107 characters instead of 108, and
# Claude Code refused that as "not logged in" because a mangled prefix is not a
# token at all. Same damage that prints "Request failed" as "Requstfailed".
#
# Requiring at least one parameter byte leaves a bare `ESC [` in place. Harmless
# inside a token match, and it never eats the character after it.
# `_ANSI` has four alternatives: CSI, OSC, charset, and a catch-all control
# class. Two of them can damage a token, and they have to be undone in order.
#
# The CSI branch is `ESC [ <params> <letter>` with the parameters optional, so a
# bare `ESC [` in front of a letter claims that letter as its terminator and
# leaves with it. That turned sk-ant-oat01-... into sk-ant-at01-..., 107
# characters instead of 108, and Claude Code refused it as "not logged in" -
# a mangled prefix is not a token at all. The same damage prints "Request
# failed" as "Requstfailed".
#
# The control class covers 0x0e-0x1f, which includes ESC itself, so it deletes a
# lone ESC and strands the `[` as visible text. Running it first splits the
# token just as badly.
_CSI_WITH_PARAMS = re.compile(r"\x1b\[[0-9;?]+[A-Za-z]")
_OSC = re.compile(r"\x1b][^\x07\x1b]*(?:\x07|\x1b\\)")
_CHARSET = re.compile(r"\x1b\([AB]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _clean_keeping_text(text: str) -> str:
    """Strip terminal noise without taking a character of real text with it."""
    text = _CSI_WITH_PARAMS.sub("", text)   # complete sequences, params and all
    text = _OSC.sub("", text)
    text = _CHARSET.sub("", text)
    text = text.replace("\x1b[", "")        # a bare CSI: two characters, not three
    return _CONTROL.sub("", text)            # only now, the leftover control bytes


# A screen, not a stream.
#
# The CLI redraws with absolute cursor moves. A real sign-in emitted
#
#     sk-ant-\x1b[10Gat01-...
#
# - write `sk-ant-`, jump to column 10, carry on with `at01-`. The `o` belongs to
# an earlier pass of the redraw and is sitting at column 9 on the screen. It is
# never adjacent to the rest in the byte stream, so deleting escapes welds
# `sk-ant-` to `at01-` and loses it: a 108-character token arrives as 107 with a
# prefix Claude Code does not recognise, and reports as "not logged in" rather
# than as invalid.
#
# No amount of regex recovers that, because the information is positional. This
# replays the moves onto a buffer and reads back what the terminal would show.
_CSI = re.compile(r"\x1b\[([0-9;?]*)([A-Za-z])")


def render_screen(raw: str) -> str:
    """What the terminal would be showing, after replaying the writes."""
    rows: list[list[str]] = [[]]
    row = col = 0

    def put(ch: str) -> None:
        nonlocal row, col
        while len(rows) <= row:
            rows.append([])
        line = rows[row]
        while len(line) <= col:
            line.append(" ")
        line[col] = ch
        col += 1

    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == "\x1b":
            match = _CSI.match(raw, i)
            if match:
                params, final = match.group(1), match.group(2)
                first = 0
                for part in params.split(";"):
                    if part.isdigit():
                        first = int(part)
                        break
                if final == "G":          # column, 1-based
                    col = max(0, first - 1)
                elif final == "H" or final == "f":
                    numbers = [int(n) for n in params.split(";") if n.isdigit()]
                    row = max(0, (numbers[0] if numbers else 1) - 1)
                    col = max(0, (numbers[1] if len(numbers) > 1 else 1) - 1)
                elif final == "A":
                    row = max(0, row - max(1, first))
                elif final == "B":
                    row += max(1, first)
                elif final == "C":
                    col += max(1, first)
                elif final == "D":
                    col = max(0, col - max(1, first))
                elif final == "K":        # erase in line
                    while len(rows) <= row:
                        rows.append([])
                    if first == 0:
                        del rows[row][col:]
                    elif first == 2:
                        rows[row] = []
                i = match.end()
                continue
            # OSC and anything else escape-shaped: consume, draw nothing.
            osc = _OSC_SEQUENCE.match(raw, i)
            if osc:
                i = osc.end()
                continue
            i += 2
            continue
        if ch == "\r":
            col = 0
        elif ch == "\n":
            row += 1
            col = 0
        elif ch == "\b":
            col = max(0, col - 1)
        elif ch >= " ":
            put(ch)
        i += 1

    return "\n".join("".join(line).rstrip() for line in rows)


_OSC_SEQUENCE = re.compile("\x1b][^\x07\x1b]*(?:\x07|\x1b\\\\)")


def _token_candidates(text: str) -> list[str]:
    """Every distinct reading of a token, best first.

    Read both ways, because neither cleaning is safe alone: the strict pass
    keeps a character the lenient one eats, and the lenient pass rejoins a token
    the strict one leaves split by a bare `ESC [`. A reading carrying the real
    `sk-ant-oat` prefix beats one that does not, then longer beats shorter - the
    CLI redraws its frame, so a short reading is a partial one.
    """
    found: list[str] = []
    for cleaned in (render_screen(text), _clean_keeping_text(text), _clean(text)):
        for match in _TOKEN_PATTERN.findall(cleaned):
            # A redraw can print a partial token and then the whole one with
            # nothing between them once the cursor moves are stripped, and every
            # character is a token character - so the two arrive welded into a
            # single over-long match that longest-first would happily prefer. A
            # real token carries its prefix once; keep the last one.
            cut = match.rfind(_TOKEN_PREFIX)
            if cut > 0:
                match = match[cut:]
            if match not in found:
                found.append(match)
    return sorted(
        found, key=lambda c: (c.startswith(_TOKEN_PREFIX), len(c)), reverse=True
    )


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
