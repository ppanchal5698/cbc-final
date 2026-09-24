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


# The pty window the CLI draws into.
#
# Wide, because the CLI hard-wraps to the column count and a CRLF through the
# middle of the authorization URL makes it unusable. Tall, because a terminal
# scrolls once the cursor leaves the bottom row and everything drawn so far
# shifts up one - while `render_screen` replays onto a buffer that only grows.
# After a scroll the two disagree about which row a line is on, and half a
# redrawn frame lands a row away from the half already there. Both numbers are
# far beyond what this flow prints, which is the point.
WINDOW_ROWS = 500
WINDOW_COLUMNS = 400


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
#
# Replaying is only faithful while the buffer and the terminal agree on where the
# rows are. A real terminal scrolls when the cursor leaves the bottom and every
# line drawn so far shifts up one; a buffer that grows on demand does not. One
# scroll and the character the CLI skipped over is on a different row from the
# rest of the token - the same missing `o`, reached a different way. Hence the
# 500-row pty in `oauth_start`: tall enough that nothing ever scrolls.
_CSI = re.compile(r"\x1b\[([0-9;?]*)([A-Za-z@])")


def render_screen(raw: str) -> str:
    """What the terminal would be showing, after replaying the writes."""
    rows: list[list[str]] = [[]]
    row = col = 0
    saved = (0, 0)

    def line_at(index: int) -> list[str]:
        while len(rows) <= index:
            rows.append([])
        return rows[index]

    def put(ch: str) -> None:
        nonlocal col
        line = line_at(row)
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
                numbers = [int(n) for n in params.split(";") if n.isdigit()]
                first = numbers[0] if numbers else 0
                if final == "G":                      # absolute column, 1-based
                    col = max(0, first - 1)
                elif final in ("H", "f"):             # absolute position
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
                elif final == "K":                    # erase in line
                    line = line_at(row)
                    if first == 0:
                        del line[col:]
                    elif first == 1:
                        line[: col + 1] = [" "] * min(col + 1, len(line))
                    else:
                        line.clear()
                elif final == "J":                    # erase in display
                    line = line_at(row)
                    if first == 0:
                        del line[col:]
                        del rows[row + 1 :]
                    elif first == 1:
                        rows[:row] = [[] for _ in range(row)]
                        line[: col + 1] = [" "] * min(col + 1, len(line))
                    else:
                        rows[:] = [[] for _ in rows]
                elif final == "s":
                    saved = (row, col)
                elif final == "u":
                    row, col = saved
                i = match.end()
                continue
            following = raw[i + 1] if i + 1 < len(raw) else ""
            if following == "]":
                osc = _OSC.match(raw, i)
                i = osc.end() if osc else i + 2
                continue
            if following == "7":                      # DECSC
                saved = (row, col)
            elif following == "8":                    # DECRC
                row, col = saved
            elif following == "M":                    # reverse index
                row = max(0, row - 1)
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


def _prefix_repairs(candidate: str) -> list[str]:
    """The same reading with the hole in its prefix filled in.

    Every token starts `sk-ant-oat`. The terminal drops characters positionally,
    so a reading can arrive with one missing from inside that prefix and the body
    perfectly intact - `sk-ant-at01-...` for `sk-ant-oat01-...`. The body cannot
    be guessed at, but the prefix is the same on every token ever issued, so the
    hole in it is fillable: find where the reading rejoins the prefix and splice
    the real one back on. A repair is offered to Claude Code like any other
    candidate, so a wrong guess costs one check and is refused.
    """
    if candidate.startswith(_TOKEN_PREFIX):
        return []
    repairs: list[str] = []
    width = len(_TOKEN_PREFIX)
    for kept in range(width):                     # leading characters that survived
        if candidate[:kept] != _TOKEN_PREFIX[:kept]:
            break
        for resume in range(kept + 1, width):     # where the reading rejoins it
            rest = _TOKEN_PREFIX[resume:]
            if not candidate[kept:].startswith(rest):
                continue
            fixed = _TOKEN_PREFIX + candidate[kept + len(rest) :]
            # A cursor jump skips a column, occasionally two. Anything claiming
            # the terminal swallowed more than that is the prefix re-aligning
            # against itself somewhere it does not belong - `sk-ant-at01-…`
            # rejoining at the second `t` yields `sk-ant-oat-at01-…`, which
            # sorts first for being longest and wastes the check.
            if 0 < len(fixed) - len(candidate) <= 2 and fixed not in repairs:
                repairs.append(fixed)
    return repairs


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
    for reading in list(found):
        for repaired in _prefix_repairs(reading):
            if repaired not in found:
                found.append(repaired)

    # Each candidate costs a CLI round trip to check, and past the first few they
    # are variations on a reading that was already wrong.
    return sorted(
        found, key=lambda c: (c.startswith(_TOKEN_PREFIX), len(c)), reverse=True
    )[:6]


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
