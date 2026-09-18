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


def _is_floor(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Constant)
        and type(node.value) is float
        and node.value == CONFIDENCE_FLOOR
    )


def _threshold_copies(tree: ast.AST) -> list[int]:
    """Lines where 0.75 is used as a *threshold*, not merely written down.

    The scan used to flag every float 0.75 anywhere, which caught two numbers in
    the seed script that are not this floor and never move with it: Hager's
    `share_of_volume`, and the custom-fabrication `divisor`. Comparing against
    the floor, or naming a variable for it, is what this rule is about - and it
    is how all five of the original copies were written.
    """
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            lines += [
                operand.lineno
                for operand in (node.left, *node.comparators)
                if _is_floor(operand)
            ]
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and _is_floor(node.value):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            named = " ".join(t.id for t in targets if isinstance(t, ast.Name)).lower()
            if any(word in named for word in ("confidence", "floor", "threshold")):
                lines.append(node.value.lineno)
    return lines


def test_no_second_copy_in_code() -> None:
    copies = [
        f"{path.relative_to(REPO)}:{line}"
        for root in (SRC, BACKEND / "scripts")
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts and path != OWNER
        for line in _threshold_copies(ast.parse(path.read_text(encoding="utf-8")))
    ]
    assert not copies, "import CONFIDENCE_FLOOR instead of writing the number:\n" + "\n".join(copies)


def test_the_narrowing_did_not_turn_the_rule_off() -> None:
    """It must still catch a real copy, and still ignore a coincidence."""
    assert _threshold_copies(ast.parse("if score < 0.75:\n    pass\n"))
    assert _threshold_copies(ast.parse("confidence_floor = 0.75\n"))
    assert not _threshold_copies(ast.parse('vendor = {"share_of_volume": 0.75}\n'))
    assert not _threshold_copies(ast.parse("divisor = 0.75\n"))


def test_the_web_row_uses_the_same_floor() -> None:
    """The line-item row cannot import a Python constant; it may not drift from it."""
    row = (REPO / "apps" / "web" / "components" / "extraction" / "line-item-row.tsx").read_text(encoding="utf-8")
    thresholds = set(re.findall(r"confidence\s*>=\s*([0-9.]+)", row))
    assert thresholds == {str(CONFIDENCE_FLOOR)}, thresholds
