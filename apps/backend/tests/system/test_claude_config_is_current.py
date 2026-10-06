"""The agent configuration has to keep up with the code it drives.

`test_agent_definitions.py` beside this already checks the machine-readable part:
tool names resolve, servers exist, the delegation rule names real agents, the
model split holds. What nothing checked is the *prose*, which is most of what an
agent actually reads - and prose goes stale silently.

It did. When the parse became trustworthy, the instructions telling agents to
distrust it and read pictures instead stayed behind. On one 24-page bid the take-off rendered two sheets
twenty-four times, hit its turn cap and produced a single patch, while the door
schedule sat parsed one call away. That cost real money for weeks, and no test
could have noticed, because every tool name in the file was still valid.

So: retired vocabulary is named here, and a path an agent is told to run has to
exist. Both fail loudly the moment the code moves on without the prose.
"""
from __future__ import annotations

import re

import pytest

from tests.shared import ROOT

CLAUDE = ROOT / ".claude"

# Words that describe a system this repo no longer is. The value is what to say
# instead, so a failure reads as an instruction rather than as a puzzle.
RETIRED = {
    "GPU-parsed": "no GPU is in the stack since LlamaParse - say 'parsed' and cite the verified score",
    "door_schedule.json": "renamed to line_items.json, which also carries Div 10 and FRP",
    "run_full_pipeline": "retired and refused by the API - autopilot chains the domain jobs",
}


def _docs():
    return sorted(p for p in CLAUDE.rglob("*.md") if "graphify-out" not in p.parts)


def _ids(paths):
    return [str(p.relative_to(ROOT)).replace("\\", "/") for p in paths]


@pytest.mark.parametrize("doc", _docs(), ids=_ids(_docs()))
def test_no_agent_is_told_about_a_system_this_no_longer_is(doc) -> None:
    text = doc.read_text(encoding="utf-8", errors="replace")
    found = [f"{word!r}: {why}" for word, why in RETIRED.items() if word in text]
    assert not found, (
        f"{doc.relative_to(ROOT)} describes a retired part of the system:\n  "
        + "\n  ".join(found)
    )


# A path in prose is either relative to the file's own directory (a skill's
# `scripts/parse_schedule.py`) or to the repository root (`apps/backend/...`).
# Both resolve; anything that resolves to neither is a path the agent cannot use.
_PATH = re.compile(r"(?<![\w/.])((?:apps|mcp-servers|scripts|infra|docs|workflows)/[\w./-]+\.\w{1,4})")


@pytest.mark.parametrize("doc", _docs(), ids=_ids(_docs()))
def test_every_file_an_agent_is_pointed_at_exists(doc) -> None:
    text = doc.read_text(encoding="utf-8", errors="replace")
    missing = sorted(
        {
            path
            for path in _PATH.findall(text)
            if not (ROOT / path).exists() and not (doc.parent / path).exists()
        }
    )
    assert not missing, (
        f"{doc.relative_to(ROOT)} points at files that are not there: {missing}. "
        "An agent told to run a script that does not exist spends its turns "
        "finding that out."
    )


def test_a_tools_cache_never_rides_into_a_sandbox_as_agent_config() -> None:
    """`.claude` is cloned into the workspace of every pass.

    `sandbox.prepare` copies the whole directory, so anything a local tool leaves
    in it is copied again on every leg of every job. One graph-indexer run left 62
    cache files there. They are gitignored, which keeps them out of the
    repository and does nothing about the copying.
    """
    from cbc.worker_kit import sandbox

    assert "graphify-out" in sandbox.AGENT_CONFIG_SKIP
    ignore = sandbox.agent_config_ignore()
    assert "graphify-out" in ignore(str(CLAUDE), ["agents", "graphify-out", "rules"])
    assert ignore(str(CLAUDE), ["agents", "rules"]) == set()


def test_the_graph_cache_is_not_committed() -> None:
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files", ".claude/graphify-out"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    ).stdout.split()
    assert not tracked, f"{len(tracked)} generated cache files are tracked under .claude/"
