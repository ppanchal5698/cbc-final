"""`.claude/hooks/_shell.py`: a command line read the way a shell reads it.

The guards matched patterns against raw command text, so quoting meant nothing
(`git commit -m "never git push"` was a push) and anything a shell does before it
runs a word went unseen (`git -C . push`, a `bash <<EOF` body, `cd .claude && rm`).
These pin the reader the guards are now built on.
"""
from __future__ import annotations

import os
import sys

import pytest

from tests.shared import ROOT

sys.path.insert(0, str(ROOT / ".claude" / "hooks"))
import _shell  # noqa: E402

CWD = str(ROOT)


def _words(text: str) -> list[list[str]]:
    return [cmd.words for cmd in _shell.parse(text, CWD)]


def test_quoted_operators_stay_inside_their_word() -> None:
    assert _words('git commit -m "fix; rm -rf build && git push"') == [
        ["git", "commit", "-m", "fix; rm -rf build && git push"]
    ]


def test_chains_pipes_and_subshells_are_separate_commands() -> None:
    assert _words("a && b || c; d | e & (f; g)") == [["a"], ["b"], ["c"], ["d"], ["e"], ["f"], ["g"]]


def test_a_heredoc_body_is_stdin_not_shell() -> None:
    [cat] = _shell.parse("cat <<'EOF' > notes.md\nnever git push\nEOF", CWD)
    assert cat.words == ["cat"] and cat.stdin == "never git push"
    assert cat.redirects == [(">", "notes.md")]


def test_a_heredoc_fed_to_a_shell_is_read_as_shell() -> None:
    assert ["git", "push", "origin", "main"] in _words("bash <<EOF\ngit push origin main\nEOF")


def test_command_substitution_and_backticks_are_followed() -> None:
    words = _words("echo $(git push) `rm x`")
    assert ["git", "push"] in words and ["rm", "x"] in words
    assert words[-1][0] == "echo" and _shell.UNKNOWN in words[-1][1]


def test_the_commit_message_heredoc_form_parses_with_a_paren_in_it() -> None:
    """Claude Code's own `git commit -m "$(cat <<'EOF' ... EOF)"`."""
    commands = _shell.parse("git commit -m \"$(cat <<'EOF'\nfix(x): a ) paren\nEOF\n)\"", CWD)
    assert [c.words[0] for c in commands] == ["cat", "git"]
    assert commands[0].stdin == "fix(x): a ) paren"


def test_cd_moves_the_commands_after_it() -> None:
    commands = _shell.parse("cd .claude && rm hooks/x.py; (cd /tmp); ls", CWD)
    assert _shell.resolve("hooks/x.py", commands[1].cwd) == (ROOT / ".claude" / "hooks" / "x.py").resolve()
    assert commands[-1].cwd == commands[1].cwd, "a subshell's cd does not leak"


def test_a_variable_set_earlier_on_the_line_is_followed() -> None:
    [echo] = _shell.parse("D=.claude/agents/x.md; echo hi > $D", CWD)
    assert echo.redirects == [(">", ".claude/agents/x.md")]


def test_wrappers_are_removed() -> None:
    assert _words("sudo -u root env -i FOO=1 nice -n 5 git push") == [["git", "push"]]
    assert _words("uv run --with requests python -c 'x'") == [["python", "-c", "x"]]
    assert _words("docker exec -w /app worker git status") == [["git", "status"]]


def test_shells_eval_powershell_xargs_and_find_run_nested_commands() -> None:
    assert ["git", "push"] in _words("sh -o pipefail -c 'git push'")
    assert ["git", "push"] in _words("eval git push")
    assert ["Send-MailMessage", "-To", "x"] in _words('powershell -NoProfile -Command "Send-MailMessage -To x"')
    assert ["cp", "{}", "dst"] in _words("echo a | xargs -I{} cp {} dst")
    assert ["rm", "-rf", _shell.UNKNOWN] in _words("xargs rm -rf")
    assert ["cp", _shell.UNKNOWN, "dst"] in _words("find /tmp -name x -exec cp {} dst \\;")


@pytest.mark.parametrize(
    "line,program",
    [
        ('python -c "import x"', "import x"),
        ('python -W ignore -c "import x"', "import x"),  # how pymupdf got past -c detection
        ('python -X utf8 -Bc "import x"', "import x"),
        ('py -3 -c "import x"', "import x"),
        ("python - <<'PY'\nimport x\nPY", "import x"),
        ("echo 'import x' | python", "import x"),
        ("python -m pip install x", None),
        ("python scripts/render_quote.py demo", None),
    ],
)
def test_the_inline_program_of_python_is_found(line: str, program: str | None) -> None:
    commands = [c for c in _shell.parse(line, CWD) if c.name.startswith("py")]
    assert _shell.python_program(commands[-1]) == program


@pytest.mark.skipif(os.name != "nt", reason="Git-Bash drive paths exist only on Windows")
def test_git_bash_drive_paths_are_the_windows_paths() -> None:
    drive, rest = ROOT.as_posix().split(":", 1)
    assert _shell.resolve(f"/{drive.lower()}{rest}/.claude", "/") == (ROOT / ".claude").resolve()
