"""Every bypass and false block the `.claude` audit found, through the real hooks.

Each case runs `pre_tool_use.py` the way Claude Code runs it - a JSON payload on
stdin, CLAUDE_PROJECT_DIR set - so the whole chain is under test, not one helper.
The bypasses all exited 0 before the guards were rebuilt on `_shell`; the false
blocks all exited 2, three of them on read-only commands of the audit itself.

The hooks are a backstop. A path assembled at run time (`'.cla' + 'ude'`) or a
mail API reached through a script nobody can read is beyond any text check; the
controls that do not depend on reading a command are in the patches README.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.shared import ROOT

HOOKS = ROOT / ".claude" / "hooks"


def _run(script: str, payload: dict, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOKS / script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT), **env},
        cwd=str(ROOT),
    )


def _bash(command: str, **env: str) -> subprocess.CompletedProcess:
    return _run("pre_tool_use.py", {"tool_name": "Bash", "tool_input": {"command": command}}, **env)


T = ".claude/agents/x.md"

# ── bypasses: each of these exited 0 ────────────────────────────────────────

PUSHES = [
    "git -C . push origin main",
    "bash <<EOF\ngit push origin main\nEOF",
    "git --git-dir=.git push",
    "git -c core.sshCommand=ssh push",
    "sh -c 'git push'",
    "echo $(git push)",
    "echo `git push`",
    "eval git push",
    "sudo -u root env FOO=1 git push",
    "git -c alias.p=push p",
    "git config alias.p push",
]

WRITES = [
    # git writes into protected paths
    "git restore .claude/settings.json",
    "git restore --source=HEAD~1 -- .claude/hooks/pre_send_quote.py",
    f"git checkout HEAD~1 -- {T}",
    "git checkout .",
    "git update-index --assume-unchanged .claude/settings.json",
    "git update-index --skip-worktree data/reference-library/margins/margin_framework.json",
    "git apply /tmp/does-not-exist.diff",  # cannot tell what it writes
    # the shell, followed through cd, variables, nesting and wrappers
    "cd .claude && rm hooks/pre_send_quote.py",
    "cd .claude; rm -f settings.json",
    f"D={T}; echo hi > $D",
    f"bash -c 'echo hi > {T}'",
    f'sh -c "echo hi > {T}"',
    f"echo /tmp/x | xargs -I{{}} cp {{}} {T}",
    f"find /tmp -name x -exec cp {{}} {T} \\;",
    "find .claude -name '*.md' -delete",
    "ln -sf /tmp/evil .claude/hooks/pre_send_quote.py",
    "dd if=/dev/zero of=.claude/settings.json",
    "tar -xzf /tmp/a.tgz -C .claude",
    'powershell -Command "Set-Content -Path .claude/settings.json -Value x"',
    # inline code
    'python -W ignore -c "import pymupdf"',
    "python -X utf8 -c 'import fitz'",
    f"uv run python - <<'PY'\nfrom pathlib import Path\nPath('{T}').write_text('x')\nPY",
    f"py -3 -c \"open('{T}','w').write('x')\"",
    f"python -c \"import os; os.replace('/tmp/x','{T}')\"",
    f"python -c \"import shutil; shutil.copy('/tmp/x','{T}')\"",
    f"node -e \"require('fs').writeFileSync('{T}','x')\"",
    f"perl -e 'open(F,\">\",\"{T}\"); print F \"x\";'",
]

SENDS = [
    'powershell -Command "Send-MailMessage -To gc@example.com -Subject Quote"',
    "Send-MailMessage -To gc@example.com -Subject Quote",
    "aws ses send-email --from a@example.com --to gc@example.com",
    "aws --region us-east-1 sesv2 send-email --content x",
    "curl https://api.resend.com/emails -d @body.json",
    "node -e \"fetch('https://api.sendgrid.com/v3/mail/send', {method: 'POST'})\"",
    "curl --url smtps://smtp.example.com --mail-rcpt gc@example.com -T quote.eml",
    "python - <<'PY'\nimport smtplib\nsmtplib.SMTP('mail.example.com')\nPY",
    "echo hi | mail -s Quote gc@example.com",
    "curl -X POST https://hooks.slack.com/services/T0/B0/x -d '{}'",
]


@pytest.mark.parametrize("command", PUSHES)
def test_a_push_in_any_spelling_is_blocked(command: str) -> None:
    result = _bash(command)
    assert result.returncode == 2, f"{command!r} got through\n{result.stderr}"
    assert "rule=git-push" in result.stderr


@pytest.mark.parametrize("command", WRITES)
def test_a_write_into_protected_data_in_any_spelling_is_blocked(command: str) -> None:
    result = _bash(command)
    assert result.returncode == 2, f"{command!r} got through\n{result.stderr}"


@pytest.mark.parametrize("command", SENDS)
def test_a_send_in_any_spelling_is_blocked(command: str) -> None:
    result = _bash(command)
    assert result.returncode == 2, f"{command!r} got through\n{result.stderr}"
    assert "NFR-1" in result.stderr


@pytest.mark.skipif(os.name != "nt", reason="Git-Bash drive paths exist only on Windows")
def test_a_git_bash_path_into_reference_data_is_blocked() -> None:
    drive, rest = ROOT.as_posix().split(":", 1)
    result = _bash(f'cp evil.json "/{drive.lower()}{rest}/data/pricebooks/index.json"')
    assert result.returncode == 2, result.stderr


def test_a_patch_that_writes_into_claude_is_not_applied(tmp_path: Path) -> None:
    patch = tmp_path / "p.diff"
    patch.write_text(
        "diff --git a/.claude/x.md b/.claude/x.md\n--- a/.claude/x.md\n+++ b/.claude/x.md\n"
        "@@ -0,0 +1 @@\n+x\n",
        encoding="utf-8",
    )
    blocked = _bash(f'git apply "{patch.as_posix()}"')
    assert blocked.returncode == 2 and "rule=git-protected-write" in blocked.stderr
    checked = _bash(f'git apply --check "{patch.as_posix()}"')
    assert checked.returncode == 0, "--check only reads the patch"


def test_a_python_script_that_imports_a_mail_library_is_blocked(tmp_path: Path) -> None:
    script = tmp_path / "send.py"
    script.write_text("import smtplib\n", encoding="utf-8")
    assert _bash(f'python "{script.as_posix()}"').returncode == 2


@pytest.mark.parametrize(
    "tool_name,tool_input",
    [
        ("mcp__slack__slack_post_message", {"channel": "c", "text": "quote"}),
        ("mcp__gmail__reply_to_message", {"id": "1", "body": "quote"}),
        ("mcp__composio__execute_tool", {"tool_slug": "GMAIL_SEND_EMAIL", "arguments": {}}),
    ],
)
def test_a_tool_that_sends_by_another_name_is_blocked(tool_name: str, tool_input: dict) -> None:
    result = _run("pre_tool_use.py", {"tool_name": tool_name, "tool_input": tool_input})
    assert result.returncode == 2, result.stderr


# ── the seeded-file rule, whatever the path's spelling and whoever owns it ────

def _seed(root: Path, project: str = "demo") -> None:
    priced = root / project / "priced"
    priced.mkdir(parents=True)
    (priced / "line_items.json").write_text(
        json.dumps({"source": "preprice.py (deterministic pre-pricing)", "lines": [{}]}),
        encoding="utf-8",
    )


@pytest.mark.parametrize("path", ["./priced/line_items.json", "projects/demo/priced/line_items.json"])
def test_a_seeded_file_cannot_be_replaced_under_another_spelling(tmp_path: Path, path: str) -> None:
    _seed(tmp_path)
    payload = {"tool_name": "mcp__artifact-storage__save_artifact",
               "tool_input": {"project": "demo", "path": path, "content": "{}"}}
    result = _run("pre_tool_use.py", payload, CBC_PROJECTS_ROOT=str(tmp_path))
    assert result.returncode == 2 and "rule=checkpoint-propose-patch" in result.stderr


def test_a_sandbox_is_not_blocked_by_a_seed_it_does_not_own(tmp_path: Path) -> None:
    """Only the run's own root counts; the live tree's seed is not the sandbox's."""
    live, sandbox = tmp_path / "live", tmp_path / "sandbox"
    _seed(live)
    (sandbox / "demo").mkdir(parents=True)
    payload = {"tool_name": "mcp__artifact-storage__save_artifact",
               "tool_input": {"project": "demo", "path": "priced/line_items.json", "content": "{}"}}
    result = _run("pre_tool_use.py", payload, CBC_PROJECTS_ROOT=str(sandbox), STORAGE_ROOT=str(live))
    assert result.returncode == 0, result.stderr


# ── false blocks: each of these exited 2 ────────────────────────────────────

ALLOWED = [
    'git commit -m "note: never git push here"',
    'git commit -m "fix; rm -rf build"',
    "git commit -m \"$(cat <<'EOF'\nfix: never git push from a run (or rm -rf)\nEOF\n)\"",
    "grep -e 'a\\|rm -rf\\|b' notes.txt",
    "grep -rn smtp_host config/",
    # Two read-only commands of the audit itself, blocked for naming a word.
    "python - <<'PY'\nkeys = ('bypass', 'smtp', 'git push')\nprint(keys)\nPY",
    "docker exec worker sh -c 'env | cut -d= -f1 | grep -iE \"smtp|ses_\"'",
    "tar -czf /tmp/b.tgz .claude",
    "sed --quiet p .claude/settings.json",
    "git checkout main",
    "git apply --stat patches/claude-audit/05-constants.patch",
    "git log --oneline -1 -- .claude",
    "cat .claude/settings.json | grep deny",
    "curl https://api.github.com/repos/x/y",
    "python scripts/render_quote.py demo",
]


@pytest.mark.parametrize("command", ALLOWED)
def test_a_command_that_only_names_a_forbidden_thing_is_allowed(command: str) -> None:
    result = _bash(command)
    assert result.returncode == 0, f"{command!r} was blocked\n{result.stderr}"


def test_an_mcp_read_named_like_a_write_is_not_one() -> None:
    """`_is_mcp_write` found `put` inside `compute_totals`."""
    payload = {"tool_name": "mcp__calc-engine__compute_totals",
               "tool_input": {"note": ".claude/settings.json"}}
    assert _run("pre_tool_use.py", payload).returncode == 0


# ── the controls that do not read a command ─────────────────────────────────

@pytest.mark.parametrize("agent,refused", [("1", True), ("", False)])
def test_the_pre_push_hook_refuses_an_agent_session(agent: str, refused: bool) -> None:
    """Claude Code sets CLAUDECODE in every command it runs; a person's terminal does not."""
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    if agent:
        env["CLAUDECODE"] = agent
    result = subprocess.run(["sh", str(ROOT / "scripts" / "git-hooks" / "pre-push")],
                            capture_output=True, text=True, env=env)
    assert (result.returncode != 0) is refused, result.stderr


# ── the audit log records who made the call ─────────────────────────────────

def test_the_audit_log_names_the_subagent_from_the_fields_claude_code_sends(tmp_path: Path) -> None:
    """Keys checked against a captured payload: subagents carry agent_type and
    agent_id, the main session neither. The hook read agent_name / subagent_type,
    which never arrive, so every line said "orchestrator"."""
    bid = tmp_path / "audit_probe_bid"
    bid.mkdir()
    base = {"tool_name": "mcp__artifact-storage__save_artifact", "session_id": "s1",
            "tool_input": {"project": "audit_probe_bid", "path": "x.json"}}
    _run("log_audit_trail.py", {**base, "tool_use_id": "toolu_1", "agent_type": "pricing-engineer",
                                "agent_id": "a1"}, CBC_PROJECTS_ROOT=str(tmp_path))
    _run("log_audit_trail.py", {**base, "tool_use_id": "toolu_2"}, CBC_PROJECTS_ROOT=str(tmp_path))
    sub, main = [json.loads(line) for line in (bid / "audit_trail.jsonl").read_text().splitlines()]
    assert (sub["agent_name"], sub["agent_id"], sub["tool_use_id"]) == ("pricing-engineer", "a1", "toolu_1")
    assert (main["agent_name"], main["agent_id"]) == ("orchestrator", None)
