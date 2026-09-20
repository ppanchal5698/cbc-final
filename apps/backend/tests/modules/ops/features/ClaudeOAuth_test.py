"""Driving the `claude setup-token` terminal prompt.

Every assertion here comes from bytes the real CLI actually emitted. The flow is
terminal-shaped rather than API-shaped, and each of these was a live bug:

  * the prompt submits on carriage return; a newline is accepted into the field
    and never sent, so the code sits there echoing asterisks until the timeout
  * the CLI positions the cursor between words and styles the token it prints, so
    text only matches once the escapes are stripped - searching the raw stream
    waits out the timeout, or throws away a token that was created perfectly well
  * a rejected code makes the CLI start a *new* authorization, so the URL on
    screen is already dead
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import pytest

# The settings router is an importable module now. This used to reach it by
# inserting ROOT/"packages" and ROOT/"services"/"platform" onto sys.path and
# importing `api.routers.settings` - the pre-cutover service layout, and the
# path hack `test_no_sys_path_insert` exists to discourage.
from cbc.modules.ops.features.ClaudeOAuth import terminal as settings_router
from cbc.modules.ops.infrastructure import secrets

ESC = chr(27)

# Captured from `claude setup-token` running on a pty inside the container.
REJECTED = (
    "\r****************-state\r\r\n\rOAuth error: Requstfailed withstatus code 400"
    "\r\rPressEntertoretry.\r\r\r"
)
PROMPT_AS_WRITTEN = (
    f"{ESC}[2GPaste{ESC}[8Gcode{ESC}[13Ghere{ESC}[18Gif{ESC}[21Gprompted{ESC}[30G>"
)
URL_AS_WRITTEN = (
    f"{ESC}]8;id=16703i4;https://claude.com/cai/oauth/authorize?code=true"
    "&client_id=9d1c250a&response_type=code&code_challenge_method=S256"
    "&state=jx8lYnJXdvxKPu0yVkrTR8uQoicJyqjaEBrMUE0mWh8\x07"
)

TOKEN = "sk-ant-oat01-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"

# The success panel, styled the way the CLI styles it.
SUCCESS_AS_WRITTEN = (
    f"{ESC}[32m✓ Long-lived authentication token created successfully!{ESC}[39m\r\n"
    f"Your OAuth token (valid for 1 year): {ESC}[1m"
    f"{TOKEN[:20]}{ESC}[22m{ESC}[1m{TOKEN[20:]}{ESC}[39m\r\n"
    "Store this token securely. You won't be able to see it again.\r\n"
)


def test_the_authorization_url_survives_its_terminal_wrapper():
    match = settings_router.URL_PATTERN.search(URL_AS_WRITTEN)
    assert match, "the URL is unreachable and sign-in cannot start"
    assert match.group(0).endswith("jx8lYnJXdvxKPu0yVkrTR8uQoicJyqjaEBrMUE0mWh8")
    assert "\x07" not in match.group(0)


def test_a_rejected_code_is_reported_in_the_cli_s_own_words():
    assert settings_router._OAUTH_ERROR.search(REJECTED)
    assert settings_router._DONE_PATTERN.search(REJECTED), (
        "without this the wait runs to the full timeout before reporting a failure"
    )


def test_the_prompt_is_only_recognisable_once_the_escapes_are_stripped():
    """The regression that made every rejected code cost 30 seconds."""
    assert not settings_router._PROMPT_PATTERN.search(PROMPT_AS_WRITTEN)
    assert settings_router._PROMPT_PATTERN.search(
        settings_router._clean(PROMPT_AS_WRITTEN)
    )


def test_a_token_split_by_styling_escapes_is_still_recovered():
    """The failure that threw away a token the CLI had already created.

    The token is printed inside a styled panel, so colour escapes land between
    its characters. A raw search finds nothing, reports "no token came back", and
    loses it - and the CLI shows it exactly once, so the sign-in has to start over.
    """
    assert not settings_router._TOKEN_PATTERN.search(
        SUCCESS_AS_WRITTEN
    ), "the raw stream hides the token; this is the bug"

    readable = settings_router._clean(SUCCESS_AS_WRITTEN)
    recovered = settings_router._TOKEN_PATTERN.search(readable)
    assert recovered and recovered.group(0) == TOKEN


def test_a_successful_creation_is_never_read_as_a_failure():
    readable = settings_router._clean(SUCCESS_AS_WRITTEN)
    assert not settings_router._OAUTH_ERROR.search(readable)
    assert settings_router._DONE_PATTERN.search(readable)


@pytest.mark.skipif(
    os.name != "posix",
    reason="select() takes only sockets on Windows, and the pty flow is POSIX-only anyway",
)
def test_read_until_stops_on_text_that_only_matches_after_cleaning():
    """So the reader tests both forms, which is what it now does."""
    read_fd, write_fd = os.pipe()

    def emit() -> None:
        time.sleep(0.1)
        os.write(write_fd, PROMPT_AS_WRITTEN.encode("utf-8"))

    threading.Thread(target=emit, daemon=True).start()
    started = time.time()
    output = settings_router._read_until(read_fd, settings_router._PROMPT_PATTERN, 10)
    elapsed = time.time() - started

    os.close(read_fd)
    os.close(write_fd)

    assert settings_router._PROMPT_PATTERN.search(settings_router._clean(output))
    assert elapsed < 5, f"returned only on timeout after {elapsed:.1f}s"


def test_a_credential_in_terminal_output_is_still_redacted():
    """Whatever the CLI echoes, it must not reach a log or an error message."""
    cleaned = secrets.redact(settings_router._clean(SUCCESS_AS_WRITTEN))
    assert TOKEN not in cleaned
    assert "[redacted]" in cleaned


def test_the_complete_rendering_of_the_token_is_the_one_chosen():
    """The bug that stored a valid token one character short.

    The CLI redraws its frame as it works, so the buffer carries the token more
    than once. An intermediate frame can have a style escape spliced into the
    middle of it, and stripping that escape takes a token character with it. The
    damaged rendering appears first, so taking the first match stored a credential
    that Claude Code rejected as an invalid bearer token - indistinguishable, from
    the outside, from a genuinely bad credential.
    """
    corrupted = TOKEN.replace("sk-ant-oat01-", "sk-ant-at01-", 1)
    buffer_text = (
        f"Your OAuth token: {corrupted}\r\n"  # an intermediate frame
        f"Your OAuth token: {TOKEN}\r\n"  # the finished frame
    )

    found = settings_router._TOKEN_PATTERN.findall(buffer_text)
    assert found[0] == corrupted, "the damaged rendering really does come first"

    chosen = sorted(set(found), key=len, reverse=True)[0]
    assert chosen == TOKEN


def test_a_lone_damaged_rendering_is_repaired_not_trusted():
    """The test above assumes a clean rendering is also on the buffer. Often it isn't.

    A real sign-in reported `Tried 1 reading(s): 107 chars sk-ant-at01-…`, and
    Claude Code answered "Not logged in - Please run /login". One reading, and it
    was the damaged one: sorting by length has nothing better to choose. A token
    whose prefix has been mangled is not recognised as a credential at all, which
    is why the CLI said no credential rather than a bad one - and why this looked
    for so long like a rejected authorization code.

    The damage is `_ANSI`'s CSI branch: the parameters are optional, so a bare
    `ESC [` in front of a letter claims that letter as its terminator and leaves
    with it. Here it eats the `o` of `oat01`.
    """
    raw = f"Your OAuth token: sk-ant-\x1b[{TOKEN.removeprefix('sk-ant-')}\r\n"

    damaged = settings_router._clean(raw)
    assert "sk-ant-at01-" in damaged, "the lenient pass really does eat the character"
    assert TOKEN not in damaged

    candidates = settings_router._token_candidates(raw)
    assert candidates, "something has to come back"
    assert candidates[0] == TOKEN, f"expected the repaired token, got {candidates[0]!r}"


def test_a_complete_rendering_still_wins_over_a_partial_one():
    """Repairing must not cost the behaviour the older test pins."""
    partial = TOKEN[:40]
    raw = f"\x1b[2K{partial}\x1b[1G{TOKEN}\r\n"

    assert settings_router._token_candidates(raw)[0] == TOKEN


def test_an_absolute_column_jump_does_not_lose_the_character_it_skips():
    """The failure that outlasted every regex fix. Bytes from a real sign-in:

        'Gyear):\r\n\x1b[1C\x1b[2Bsk-ant-\x1b[10Gat'

    `ESC [ n G` is CHA - move to an absolute column. The CLI writes `sk-ant-`,
    jumps, and carries on with `at01-`. The character it skipped belongs to an
    earlier pass of the redraw and is sitting on the *screen*, never adjacent to
    the rest in the byte stream. Deleting escapes welds the two together and
    loses it: a 108-character token arrived as 107 with a prefix Claude Code does
    not recognise, reported as "not logged in" rather than as an invalid token -
    which is what made this read as a rejected authorization code for so long.

    Positional damage needs the position modelled. Regex cannot do it.
    """
    # `sk-ant-` is 7 characters, so the redraw resumes at 0-based column 8.
    raw = TOKEN + "\r" + "sk-ant-" + "\x1b[9G" + TOKEN[8:]

    welded = settings_router._clean(raw)
    # The redraw welds `sk-ant-` to what follows the jump, skipping the column
    # the earlier pass had written. That damaged reading is what used to be sent.
    assert "sk-ant-at01-" in welded, "stripping escapes really does lose the character"

    assert settings_router.render_screen(raw).startswith(TOKEN)
    assert settings_router._token_candidates(raw)[0] == TOKEN


def test_the_renderer_replays_the_moves_the_cli_actually_uses():
    """Each of these appeared in a captured stream."""
    render = settings_router.render_screen
    assert render("abc\rX") == "Xbc"                    # carriage return rewrites
    assert render("abcdef\x1b[3Gxy") == "abxyef"        # absolute column
    assert render("abc\x1b[2Dxy") == "axy"              # cursor back, overwriting
    assert render("ab\x1b[2Ccd") == "ab  cd"            # cursor forward
    assert render("abc\x1b[1;1Hz") == "zbc"             # absolute position
    assert render("abcdef\x1b[4G\x1b[K") == "abc"      # erase to end of line

    assert render("abc\x1b7xyz\x1b8Q") == "abcQyz"      # save and restore cursor
    assert render("abc\x1b[s\x1b[3Gz\x1b[uW") == "abzW"  # the CSI spelling of it
    assert render("aa\r\nbb\r\ncc\x1b[1;3H\x1b[0J") == "aa"  # erase to end of screen


def test_the_terminal_is_too_tall_to_scroll():
    """The renderer is only faithful while no line has moved.

    A terminal scrolls when the cursor leaves the bottom row: every line drawn
    so far shifts up one, and the CLI - which tracks the real screen - addresses
    them at their new rows. `render_screen` replays onto a buffer that only ever
    grows, so after one scroll the half of a frame drawn before it sits a row
    away from the half drawn after. That is the same lost character as the
    column jump, reached from the other side, and no care in the renderer fixes
    it. Being taller than the flow can print does.
    """
    assert settings_router.WINDOW_ROWS >= 200
    assert settings_router.WINDOW_COLUMNS > len(TOKEN) + 60


def test_the_prefix_is_only_repaired_where_the_damage_is_plausible():
    """A repair is a guess, and an unbounded one costs the real token its turn.

    The prefix can re-align against itself: `sk-ant-at01-...` rejoining at the
    second `t` of `oat` yields `sk-ant-oat-at01-...`, which is longer, carries
    the prefix, and therefore sorts ahead of the correct repair. Each candidate
    is a CLI round trip, so a wrong one is not free. A cursor jump skips a
    column or two; anything claiming more is the alignment, not the terminal.
    """
    damaged = "sk-ant-" + TOKEN[8:]
    repairs = settings_router._prefix_repairs(damaged)

    assert repairs == [TOKEN], f"expected just the one-character repair, got {repairs!r}"
    assert settings_router._prefix_repairs(TOKEN) == [], "an intact token needs nothing"


async def test_the_check_runs_against_the_candidate_not_the_env_file(monkeypatch):
    """`build_env` answers a different question than this one.

    It resolves what *would* run, where the process environment outranks `.env`
    and `.env` outranks the stored value. Here the question is whether this
    particular reading works, and a CLAUDE_CODE_OAUTH_TOKEN left in `.env` by an
    earlier attempt silently answered it instead - the same stale value checked
    against every candidate, failing identically however well each was scraped.
    A stale token and a mangled one both report "Not logged in - Please run
    /login", so there was nothing in the failure to tell them apart.
    """
    from cbc.modules.ops.features import ClaudeOAuth
    from cbc.modules.ops.api import claude_cli

    monkeypatch.setenv("CBC_ENV_FILE", str(Path(__file__).with_name("no-such.env")))
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-LEFT-OVER-FROM-LAST-TIME")

    checked: list[str | None] = []

    def record(env, redact=None, settings=None):
        checked.append(env.get("CLAUDE_CODE_OAUTH_TOKEN"))
        return None if env.get("CLAUDE_CODE_OAUTH_TOKEN") == TOKEN else "Not logged in"

    monkeypatch.setattr(claude_cli, "preflight", record)

    assert await ClaudeOAuth._first_working_token([TOKEN]) == TOKEN
    assert checked == [TOKEN], f"checked {checked!r} instead of the candidate"
