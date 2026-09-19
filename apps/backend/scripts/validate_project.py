#!/usr/bin/env python3
"""Pre-flight and artifact checks for the CBC Estimating Copilot.

    python apps/backend/scripts/validate_project.py --all
    python apps/backend/scripts/validate_project.py --check-extraction <project>
    python apps/backend/scripts/validate_project.py --check-pricing <project>
    python apps/backend/scripts/validate_project.py --check-proposal <project>
    python apps/backend/scripts/validate_project.py --check-delivery <project>
    python apps/backend/scripts/validate_project.py --demo

--all runs the pre-flight: reference-library JSON valid, price books present and
not stale, MCP servers importable, hooks present.

--check-extraction validates one project's extracted/*.json against the required
fields. It is also invoked by the post_extraction_validate.py PostToolUse hook,
which warns rather than blocks. The worker calls validate_job_artifacts() before
sync and fails the job on errors.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime

from cbc.shared.paths import pricebook_dir, reference_dir, repo_root, storage_root  # noqa: E402

# The repository root: mcp-servers/ and .claude/ are there, not beside this script.
ROOT = repo_root()

# The artifact checks are domain rules and live in the domain. This file is the
# command-line front for them, plus the pre-flight that checks this checkout -
# servers present, hooks executable, reference data current - which is a
# property of the working copy and not of any project.
from cbc.modules.ops.api.freshness import load_sync  # noqa: E402
from cbc.modules.extraction.api.validation.artifacts import (  # noqa: E402
    ARTIFACT_CHECKS,
    BBOX_COVERAGE,
    HARD_FIELDS,
    PRICING_GROUP_TYPES,
    PRICING_LINE_FIELDS,
    SOFT_FIELDS,
    UNCHECKED_JOB_TYPES,
    check_bboxes_are_real,
    check_extraction,
    check_delivery_readiness,
    check_pricing,
    check_proposal,
    validate_job_artifacts,
)

__all__ = [
    "ARTIFACT_CHECKS",
    "BBOX_COVERAGE",
    "HARD_FIELDS",
    "PRICING_GROUP_TYPES",
    "PRICING_LINE_FIELDS",
    "SOFT_FIELDS",
    "UNCHECKED_JOB_TYPES",
    "check_all",
    "check_bboxes_are_real",
    "check_extraction",
    "check_delivery_readiness",
    "check_pricing",
    "check_proposal",
    "validate_job_artifacts",
]

REFERENCE = reference_dir()
PRICEBOOKS = pricebook_dir()
# Mirrors .mcp.json. `pricebook` was here until it turned out to be a pure alias
# over `catalog` and was deleted; the pre-flight was still checking for it.
SERVERS = [
    "pdf-tools",
    "catalog",
    "catalog-docs",
    "calc-engine",
    "artifact-storage",
    "p21-connector",
    "reference",
    "bid-docs",
]
HOOKS = [
    "pre_send_quote.py",
    "pre_delete_guard.py",
    "post_extraction_validate.py",
    "post_quote_format.py",
    "log_audit_trail.py",
]
REQUIRED_REFERENCE = [
    "hardware_sets/hager_top10_stock.json",
    "hardware_sets/allegion_stock.json",
    "hardware_sets/custom_other_matrix.json",
    "margins/margin_framework.json",
    "multipliers/vendor_tiers.json",
    "multipliers/special_customer_margins.json",
    "frame_depths/wall_type_to_depth.json",
    "finishes/finish_crosswalk.json",
    "frp_constants/conversion_constants.json",
    "adders/manual_adders.json",
]

def _emit(problems: list[str], warnings: list[str]) -> int:
    for warning in warnings:
        print(f"WARN  {warning}")
    for problem in problems:
        print(f"ERROR {problem}")
    if problems:
        print(f"\n{len(problems)} error(s), {len(warnings)} warning(s).")
        return 1
    print(f"\nOK - {len(warnings)} warning(s).")
    return 0

def check_all() -> int:
    problems: list[str] = []
    warnings: list[str] = []

    for relative in REQUIRED_REFERENCE:
        path = REFERENCE / relative
        if not path.exists():
            problems.append(f"missing reference file: {relative}")
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"invalid JSON in {relative}: {exc}")
            continue
        if payload.get("status") == "PENDING":
            warnings.append(f"{relative} is PENDING - {payload.get('blocking', 'awaiting CBC input')}")

    index_path = PRICEBOOKS / "index.json"
    if not index_path.exists():
        problems.append("pricebooks/index.json missing - the pricebook server has nothing to search")
    else:
        index = json.loads(index_path.read_text(encoding="utf-8"))
        books = index.get("pricebooks", [])
        if not books:
            problems.append("pricebooks/index.json lists no price books")
        for book in books:
            if not (PRICEBOOKS / book["file"]).exists():
                problems.append(f"price book listed but missing on disk: {book['file']}")
                continue
            effective = book.get("effective_date")
            if not effective:
                warnings.append(f"{book['file']} has no effective date recorded")
                continue
            age = (date.today() - datetime.fromisoformat(effective).date()).days
            if age > load_sync().catalog_stale_days:
                warnings.append(f"{book['file']} is {age} days old (effective {effective})")

    for name in SERVERS:
        server = ROOT / "mcp-servers" / name / "server.py"
        if not server.exists():
            problems.append(f"MCP server missing: {name}/server.py")
            continue
        result = subprocess.run(
            [sys.executable, str(server), "--selftest"], capture_output=True, text=True
        )
        if result.returncode != 0:
            problems.append(f"MCP server {name} failed selftest: {result.stderr.strip()[:200]}")

    for hook in HOOKS:
        if not (ROOT / ".claude" / "hooks" / hook).exists():
            problems.append(f"guardrail hook missing: {hook}")

    settings = ROOT / ".claude" / "settings.json"
    if not settings.exists():
        problems.append(".claude/settings.json missing")
    else:
        try:
            json.loads(settings.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f".claude/settings.json is not valid JSON: {exc}")

    return _emit(problems, warnings)

def _demo() -> None:
    """Runnable check: the extraction validator's field logic."""
    import shutil

    project_dir = storage_root() / "_validate_demo"
    (project_dir / "extracted").mkdir(parents=True, exist_ok=True)
    target = project_dir / "extracted" / "door_schedule.json"
    try:
        target.write_text(
            json.dumps(
                {
                    "openings": [
                        {
                            "door_number": "01",
                            "size": "3670",
                            "source_page": 14,
                            "confidence": 0.55,
                            "bbox": [10, 20, 100, 40],
                            "page_size": {"width": 2592, "height": 1728},
                            "handing": None,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        problems, warnings = check_extraction("_validate_demo")
        assert not problems, problems
        assert warnings, "soft-missing fields must warn"

        target.write_text(
            json.dumps({"openings": [{"size": "3670", "confidence": 0.9}]}), encoding="utf-8"
        )
        problems, _ = check_extraction("_validate_demo")
        assert problems, "missing door_number must be an error"

        target.write_text(json.dumps([{"door_number": "01"}]), encoding="utf-8")
        problems, _ = check_extraction("_validate_demo")
        assert any("bare array" in p for p in problems)
    finally:
        shutil.rmtree(project_dir, ignore_errors=True)
    print("validate_project demo OK")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="Run the pre-flight checks")
    parser.add_argument("--check-extraction", metavar="PROJECT")
    parser.add_argument("--check-pricing", metavar="PROJECT")
    parser.add_argument("--check-proposal", metavar="PROJECT")
    parser.add_argument("--check-delivery", metavar="PROJECT")
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()

    if args.demo:
        _demo()
        return 0
    if args.check_extraction:
        problems, warnings = check_extraction(args.check_extraction)
        return _emit(problems, warnings)
    if args.check_pricing:
        problems, warnings = check_pricing(args.check_pricing, require_hardware_sets=True)
        return _emit(problems, warnings)
    if args.check_proposal:
        problems, warnings = check_proposal(args.check_proposal)
        return _emit(problems, warnings)
    if args.check_delivery:
        problems, warnings = check_delivery_readiness(args.check_delivery)
        return _emit(problems, warnings)
    return check_all()


if __name__ == "__main__":
    sys.exit(main())
