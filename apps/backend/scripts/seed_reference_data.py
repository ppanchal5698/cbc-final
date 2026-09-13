#!/usr/bin/env python3
"""Seed Mongo referenceData from REFERENCE_DIR JSON (fixtures).

Default: insert missing families only (operator edits win).
  python scripts/seed_reference_data.py
  python scripts/seed_reference_data.py --force   # overwrite all from seed
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing family documents from seed JSON",
    )
    args = parser.parse_args()

    from cbc.db import ensure_indexes
    from cbc.modules.pricing.api.reference_store import FAMILIES, ensure_reference_seed

    await ensure_indexes()
    seeded = await ensure_reference_seed(force=args.force)
    print(f"families known: {len(FAMILIES)}")
    print(f"seeded/updated: {len(seeded)}" + (f" ({', '.join(seeded)})" if seeded else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
