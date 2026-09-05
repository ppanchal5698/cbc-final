"""Hook helpers and settings alignment from the log vs .claude audit."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from tests.shared import ROOT

HOOKS = ROOT / ".claude" / "hooks"


def test_artifact_path_from_save_artifact() -> None:
    sys.path.insert(0, str(HOOKS))
    from _artifact_path import project_path_from_tool  # noqa: WPS433

    assert project_path_from_tool(
        "mcp__artifact-storage__save_artifact",
        {"project": "test_bid", "path": "extracted/door_schedule.json", "content": "{}"},
    ) == ("test_bid", "extracted/door_schedule.json")


def test_artifact_path_from_write() -> None:
    sys.path.insert(0, str(HOOKS))
    from _artifact_path import project_path_from_tool  # noqa: WPS433

    assert project_path_from_tool(
        "Write",
        {"file_path": "/app/projects/test_bid/priced/line_items.json", "content": "{}"},
    ) == ("test_bid", "priced/line_items.json")


def test_log_audit_trail_mirrors_to_claude_log() -> None:
    source = (HOOKS / "log_audit_trail.py").read_text(encoding="utf-8")
    assert "SESSION_LOG" in source
    assert "HOOK audit" in source
    assert "claude.log" in source


def test_save_artifact_rejects_placeholder_in_source() -> None:
    source = (ROOT / "mcp-servers" / "artifact-storage" / "server.py").read_text(
        encoding="utf-8"
    )
    assert "{file_content}" in source
    assert "refusing placeholder content" in source


def test_settings_json_is_valid() -> None:
    settings_path = ROOT / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "hooks" in settings
    assert "permissions" in settings


def test_settings_post_tool_use_includes_save_artifact() -> None:
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    matchers = [
        block["matcher"]
        for block in settings["hooks"]["PostToolUse"]
        if "matcher" in block
    ]
    # mcp__.* covers save_artifact; do not require the tool name in the matcher.
    assert any("mcp__" in matcher for matcher in matchers)
    assert len(settings["hooks"]["PreToolUse"]) == 1
    assert len(settings["hooks"]["PostToolUse"]) == 1
    assert len(settings["hooks"]["PreToolUse"][0]["hooks"]) == 1
    assert len(settings["hooks"]["PostToolUse"][0]["hooks"]) == 1


def _load_post_tool_use():
    """Load the hook under a private name.

    Its three steps are shared modules; loading a private copy keeps a
    monkeypatched `check` from leaking into any other test.
    """
    import importlib.util

    if str(HOOKS) not in sys.path:
        sys.path.insert(0, str(HOOKS))
    spec = importlib.util.spec_from_file_location(
        "_isolated_post_tool_use", HOOKS / "post_tool_use.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_post_tool_use_isolates_its_steps_and_audits_first(monkeypatch) -> None:
    """One step crashing must not take the audit trail down with it.

    These were three separate PostToolUse processes, so a crash in one could not
    reach the other two. Merging them into a single process for latency removed
    that isolation silently: with the steps called in a bare sequence, a raise in
    `post_extraction_validate` skipped `log_audit_trail` entirely and propagated
    out of the hook. NFR-3 says every tool call is recorded, so the audit trail
    runs first and every step is wrapped.
    """
    module = _load_post_tool_use()
    calls: list[str] = []

    def boom(payload: dict) -> None:
        calls.append("validate")
        raise RuntimeError("post_extraction_validate blew up")

    monkeypatch.setattr(module.post_extraction_validate, "check", boom)
    monkeypatch.setattr(module.post_quote_format, "check", lambda p: calls.append("format"))
    monkeypatch.setattr(module.log_audit_trail, "check", lambda p: calls.append("audit"))

    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": "projects/demo/extracted/door_schedule.json"},
    }

    assert module.check(payload) == 0, "a PostToolUse hook must never block the pipeline"
    assert "audit" in calls, "NFR-3: the audit record was lost when a sibling raised"
    assert calls[0] == "audit", "the audit trail runs before anything that can fail"
    assert "format" in calls, "one step raising must not skip the next"


def _run_pre_tool_use(payload: dict) -> int:
    import os
    import subprocess

    proc = subprocess.run(
        [sys.executable, str(HOOKS / "pre_tool_use.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT)},
        cwd=str(ROOT),
    )
    return proc.returncode


def test_pre_tool_use_blocks_a_send() -> None:
    assert (
        _run_pre_tool_use(
            {"tool_name": "Bash", "tool_input": {"command": "sendmail user@example.com"}}
        )
        == 2
    )


def test_pre_tool_use_blocks_a_delete_outside_projects() -> None:
    assert (
        _run_pre_tool_use(
            {"tool_name": "Bash", "tool_input": {"command": "rm -rf /tmp/cbc-not-a-bid"}}
        )
        == 2
    )


def test_pre_tool_use_blocks_inline_fitz_dash_c() -> None:
    assert (
        _run_pre_tool_use(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        "python3 -c \"import fitz; "
                        "fitz.open('projects/x/uploads/raw/a.pdf')\""
                    )
                },
            }
        )
        == 2
    )


def test_pre_tool_use_blocks_inline_fitz_heredoc() -> None:
    command = "python3 << 'EOF'\nimport fitz\nfitz.open('uploads/raw/a.pdf')\nEOF"
    assert (
        _run_pre_tool_use({"tool_name": "Bash", "tool_input": {"command": command}})
        == 2
    )


def test_pre_tool_use_allows_parse_schedule_script() -> None:
    assert (
        _run_pre_tool_use(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        "python .claude/skills/extract-door-schedule/"
                        "scripts/parse_schedule.py --page 15"
                    )
                },
            }
        )
        == 0
    )


def test_pre_tool_use_blocks_python_write_to_pricebooks() -> None:
    assert (
        _run_pre_tool_use(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        "python3 -c \"from pathlib import Path; "
                        "Path('pricebooks/x.csv').write_text('hi')\""
                    )
                },
            }
        )
        == 2
    )


def test_pre_tool_use_allows_mentioning_pricebooks_without_writing() -> None:
    assert (
        _run_pre_tool_use(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "python3 -c \"print('see pricebooks/')\""},
            }
        )
        == 0
    )
