"""NFR-2's confidence floor has one owner: pricing's `confidence.CONFIDENCE_FLOOR`.

It was written out five times - quoting's matching rules, catalog's match cache,
the review flags, extraction's opening status and the review-summary script - one
of them a bare `0.75` a few lines from the constant declared for it. A threshold
that exists in five places moves in four.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from cbc.modules.pricing.api.confidence import CONFIDENCE_FLOOR

SRC = Path(__file__).resolve().parents[2] / "src" / "cbc"
BACKEND = SRC.parents[1]
REPO = BACKEND.parents[1]
OWNER = SRC / "modules" / "pricing" / "api" / "confidence.py"


def test_the_floor_is_the_rule() -> None:
    assert CONFIDENCE_FLOOR == 0.75, ".claude/rules/accuracy-trust.md: below 0.75 is flagged"


def test_no_second_copy_in_code() -> None:
    copies = [
        f"{path.relative_to(REPO)}:{node.lineno}"
        for root in (SRC, BACKEND / "scripts")
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts and path != OWNER
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant) and type(node.value) is float and node.value == CONFIDENCE_FLOOR
    ]
    assert not copies, "import CONFIDENCE_FLOOR instead of writing the number:\n" + "\n".join(copies)


def test_the_web_row_uses_the_same_floor() -> None:
    """The line-item row cannot import a Python constant; it may not drift from it."""
    row = (REPO / "apps" / "web" / "components" / "extraction" / "line-item-row.tsx").read_text(encoding="utf-8")
    thresholds = set(re.findall(r"confidence\s*>=\s*([0-9.]+)", row))
    assert thresholds == {str(CONFIDENCE_FLOOR)}, thresholds
