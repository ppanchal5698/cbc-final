#!/usr/bin/env python3
"""Import an NR-6 top-10 stock list into reference-library/hardware_sets/.

CBC still owes the authoritative stock list; until it arrives, this script
validates and installs a candidate file (such as the draft harvested from the
Hager price book).

    python scripts/import_stock_list.py reference-library/hardware_sets/hager_top10_stock.json
    python scripts/import_stock_list.py --vendor hager path/to/cbc_stock.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET_DIR = ROOT / "reference-library" / "hardware_sets"


def validate(payload: dict) -> list[str]:
    errors: list[str] = []
    if not payload.get("vendor"):
        errors.append("missing vendor")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        errors.append("items must be a non-empty list")
        return errors
    coded = [item for item in items if isinstance(item, dict) and item.get("part_number")]
    if not coded:
        errors.append("at least one item must include part_number")
    return errors


def normalize_items(payload: dict) -> dict:
    """Drop placeholder rows that have no part number yet (NR-6 pending)."""
    items = payload.get("items") or []
    kept = [item for item in items if isinstance(item, dict) and item.get("part_number")]
    return {**payload, "items": kept}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="JSON stock list to import")
    parser.add_argument(
        "--vendor",
        help="Vendor key for the output filename (defaults to payload vendor, lowercased)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate only; do not write",
    )
    args = parser.parse_args()

    if not args.source.exists():
        print(f"missing source file: {args.source}", file=sys.stderr)
        return 1

    payload = json.loads(args.source.read_text(encoding="utf-8"))
    errors = validate(payload)
    if errors:
        for problem in errors:
            print(f"invalid: {problem}", file=sys.stderr)
        return 1

    vendor_key = (args.vendor or str(payload["vendor"])).strip().lower().replace(" ", "_")
    target = TARGET_DIR / f"{vendor_key}_top10_stock.json"

    if args.dry_run:
        normalized = normalize_items(payload)
        print(
            f"valid - would write {len(normalized['items'])} coded item(s) to {target} "
            f"({len(payload['items']) - len(normalized['items'])} placeholder row(s) skipped)"
        )
        return 0

    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    normalized = normalize_items(payload)
    target.write_text(json.dumps(normalized, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {target} ({len(normalized['items'])} items)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
