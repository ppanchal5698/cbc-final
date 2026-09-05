"""The agent runtime has exactly one source.

`agent-runtime/` was a byte-identical copy of `.claude/` - 57 files, 180 KB, kept
in sync by nothing. Worse than redundant: its own `settings.json` registered the
hooks at `.claude/hooks`, so the files in `agent-runtime/hooks/` never executed,
and `infra/docker-compose.yml` bind-mounts `.claude` live while the image baked
`agent-runtime` at build time - so inside a running container the two drifted
apart silently.

The image now derives `/app/agent-runtime` from `/app/.claude` with `cp -a`.
These tests fail if a second copy ever comes back.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tests.shared import ROOT

# Trees that must exist exactly once in the source. `.claude` is the agent
# runtime; the image copies it, the repo does not.
SINGLE_SOURCE = (".claude",)


def test_no_second_copy_of_the_agent_runtime() -> None:
    assert not (ROOT / "agent-runtime").exists(), (
        "agent-runtime/ is back. It is built from .claude/ in the Dockerfile; "
        "a copy in the source tree will drift and its hooks will not run."
    )


def _fingerprint(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        out[str(path.relative_to(root)).replace("\\", "/")] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    return out


@pytest.mark.parametrize("tree", SINGLE_SOURCE)
def test_the_single_source_tree_is_not_duplicated_elsewhere(tree: str) -> None:
    """No other directory in the repo holds the same file set."""
    source = _fingerprint(ROOT / tree)
    assert source, f"{tree} is empty or missing"

    skip = {".git", ".venv", "node_modules", "__pycache__", "data", "tests", tree}
    for candidate in ROOT.iterdir():
        if not candidate.is_dir() or candidate.name in skip:
            continue
        other = _fingerprint(candidate)
        if not other:
            continue
        shared = set(source) & set(other)
        identical = [k for k in shared if source[k] == other[k]]
        assert len(identical) < 5, (
            f"{candidate.name}/ duplicates {len(identical)} files from {tree}/ "
            f"byte for byte, e.g. {sorted(identical)[:3]}"
        )
