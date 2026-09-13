#!/usr/bin/env python3
"""Validate priced artifacts and render quotation.html.

    python scripts/validate_and_render_quote.py <project>

Runs pricing validation, then calls render_quote.py. Exits non-zero with clear
errors when line_items.json is missing required fields.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from cbc.modules.extraction.api.validation import check_pricing  # noqa: E402

RENDER_SCRIPT = (
    ROOT / ".claude" / "skills" / "generate-quotation" / "scripts" / "render_quote.py"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", help="Project slug under projects/")
    args = parser.parse_args()

    problems, warnings = check_pricing(args.project, require_hardware_sets=False)
    for warning in warnings:
        print(f"WARN  {warning}", file=sys.stderr)
    if problems:
        for problem in problems:
            print(f"ERROR {problem}", file=sys.stderr)
        return 1

    if not RENDER_SCRIPT.exists():
        print(f"ERROR render script missing: {RENDER_SCRIPT}", file=sys.stderr)
        return 1

    result = subprocess.run(
        [sys.executable, str(RENDER_SCRIPT), args.project],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        return result.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
