"""The PostToolUse hooks find the bid where it actually lives.

All three built `<repo>/projects/<bid>`, which stopped existing when bids moved
under `data/projects`. The audit trail then recorded nothing, the validator
called every checkpoint save "missing after write", and the formatter never ran.
Each test runs the real hook entry point against a throwaway repo layout.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.shared import ROOT

HOOKS = ROOT / ".claude" / "hooks"
VALID_SCOPE = ROOT / "apps/backend/tests/fixtures/projects/bid_set_first_real_run/extracted/scope_summary.json"
SAVE = "mcp__artifact-storage__save_artifact"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A checkout-shaped tree with one bid under data/projects - the default root."""
    (tmp_path / "data" / "projects" / "demo_bid" / "extracted").mkdir(parents=True)
    return tmp_path


def _post_tool_use(repo: Path, payload: dict) -> subprocess.CompletedProcess:
    # No CBC_PROJECTS_ROOT or STORAGE_ROOT: the hook has to find data/projects
    # on its own, the way an interactive session does.
    env = {k: v for k, v in os.environ.items() if k not in ("CBC_PROJECTS_ROOT", "STORAGE_ROOT")}
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    return subprocess.run(
        [sys.executable, str(HOOKS / "post_tool_use.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(repo),
    )


def test_the_audit_trail_appends_to_the_bid_under_data_projects(repo: Path) -> None:
    trail = repo / "data/projects/demo_bid/audit_trail.jsonl"
    payload = {
        "tool_name": "Read",
        "tool_input": {"file_path": str(repo / "data/projects/demo_bid/extracted/x.json")},
        "session_id": "s-1",
    }

    assert _post_tool_use(repo, payload).returncode == 0
    lines = trail.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and lines[0].strip()
    assert json.loads(lines[0])["tool_name"] == "Read"


def test_the_validator_passes_a_valid_checkpoint_save(repo: Path) -> None:
    shutil.copy(VALID_SCOPE, repo / "data/projects/demo_bid/extracted/scope_summary.json")
    payload = {"tool_name": SAVE, "tool_input": {"project": "demo_bid", "path": "extracted/scope_summary.json"}}

    result = _post_tool_use(repo, payload)
    assert result.returncode == 0, result.stderr


def test_the_validator_blocks_an_invalid_checkpoint_save(repo: Path) -> None:
    (repo / "data/projects/demo_bid/extracted/scope_summary.json").write_text('{"nonsense": 1}', encoding="utf-8")
    payload = {"tool_name": SAVE, "tool_input": {"project": "demo_bid", "path": "extracted/scope_summary.json"}}

    result = _post_tool_use(repo, payload)
    assert result.returncode == 2
    assert "missing after write" not in result.stderr


def test_the_validator_ignores_a_read_of_a_checkpoint(repo: Path) -> None:
    """A `cat` names the path too; it is not a save, and must not be judged as one."""
    (repo / "data/projects/demo_bid/extracted/scope_summary.json").write_text('{"nonsense": 1}', encoding="utf-8")
    payload = {"tool_name": "Bash", "tool_input": {"command": "cat data/projects/demo_bid/extracted/scope_summary.json"}}

    assert _post_tool_use(repo, payload).returncode == 0


def test_the_formatter_formats_the_bids_quotation(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither prettier nor pyhtmlbeautifier is installed locally or in the image,
    so the formatter is stubbed: what is under test is that the hook finds the
    bid's quotation.html and hands that path to the formatter."""
    from tests.shared import load_module

    quote = repo / "data/projects/demo_bid/quotation.html"
    quote.write_text("<html><body><p>x</p></body></html>", encoding="utf-8")
    monkeypatch.syspath_prepend(str(HOOKS))
    monkeypatch.delenv("CBC_PROJECTS_ROOT", raising=False)
    monkeypatch.setenv("STORAGE_ROOT", str(repo / "data/projects"))
    hook = load_module("post_quote_format", HOOKS / "post_quote_format.py")
    formatted: list[str] = []
    monkeypatch.setattr(hook.shutil, "which", lambda name: "prettier" if name == "prettier" else None)
    monkeypatch.setattr(hook.subprocess, "run", lambda args, **_: formatted.append(args[-1]))

    hook.check({"tool_name": SAVE, "tool_input": {"project": "demo_bid", "path": "quotation.html"}})
    assert formatted == [str(quote)]
