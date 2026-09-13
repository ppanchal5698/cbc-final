"""Docker copies `.claude` to `/app/agent-runtime`; source must stay single."""
from __future__ import annotations

from pathlib import Path

from tests.shared import ROOT


def test_dockerfile_copies_claude_to_agent_runtime() -> None:
    dockerfiles = [
        ROOT / "apps" / "backend" / "Dockerfile",
        ROOT / "infra" / "Dockerfile",
    ]
    text = "\n".join(
        path.read_text(encoding="utf-8") for path in dockerfiles if path.is_file()
    )
    assert ".claude" in text
    assert "agent-runtime" in text


def test_agent_runtime_is_not_a_second_source_tree() -> None:
    assert not (ROOT / "agent-runtime").exists()
