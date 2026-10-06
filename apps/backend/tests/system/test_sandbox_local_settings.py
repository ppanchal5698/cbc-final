"""A developer's own Claude settings never reach a pipeline run.

Compose bind-mounts the host's `.claude/` into every container, and the sandbox
copies `.claude/` into each run - so `.claude/settings.local.json`, the file a
developer edits for their own session, rode along. A blanket allow there, or
`disableAllHooks`, would have applied to every run and could switch the
product's guards off.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from cbc.worker_kit import sandbox


def test_the_sandbox_copy_leaves_local_settings_behind(tmp_path: Path) -> None:
    source = tmp_path / "repo" / ".claude"
    (source / "hooks").mkdir(parents=True)
    (source / "settings.json").write_text("{}", encoding="utf-8")
    (source / "settings.local.json").write_text('{"disableAllHooks": true}', encoding="utf-8")
    (source / "hooks" / "pre_tool_use.py").write_text("", encoding="utf-8")

    target = tmp_path / "workspace" / ".claude"
    shutil.copytree(source, target, ignore=sandbox.agent_config_ignore())

    assert (target / "settings.json").is_file()
    assert (target / "hooks" / "pre_tool_use.py").is_file()
    assert not (target / "settings.local.json").exists()
