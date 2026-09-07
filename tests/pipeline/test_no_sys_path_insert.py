"""Installed packages must not edit sys.path at import time.

`pip install -e .` and `pip install -e ./mcp-servers` make `cbc` and `_runtime`
importable. Editing sys.path in packages/, services/, scripts/, or mcp-servers/
is the old failure mode this guard exists to prevent.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.shared import ROOT

# Trees that must stay free of path hacks. tests/ and .claude/hooks may still
# load free-standing scripts by path via importlib; that is not this check.
GUARDED = ("packages", "services", "scripts", "mcp-servers")
PATTERN = re.compile(r"sys\.path\.insert\s*\(")


def test_no_sys_path_insert_in_installable_trees() -> None:
    offenders: list[str] = []
    for tree in GUARDED:
        root = ROOT / tree
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            if PATTERN.search(text):
                offenders.append(path.relative_to(ROOT).as_posix())
    assert not offenders, (
        "sys.path.insert found in installable trees "
        f"(use the editable install instead): {offenders}"
    )
