#!/usr/bin/env python3
"""Apply pending database migrations, or say what would run.

The runner itself (`cbc.persistence.migrations`) is handed a database and never
looks for one - it sits below `cbc.db` in the dependency order. This script is
the operator entry point that knows how to make a client.

Startup does the same thing automatically (`cbc.db.ensure_indexes`), so this is
for the times you want to see the ledger, or to migrate without booting a service.

    python scripts/migrate.py --status
    python scripts/migrate.py
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from cbc.shared.mongo import database
from cbc.persistence import migrations


async def _status() -> int:
    db = database()
    done = await migrations.applied_versions(db)
    catalogue = migrations.discover()
    if not catalogue:
        print("no migrations defined")
        return 0
    for migration in catalogue:
        mark = "applied" if migration.version in done else "PENDING"
        print(f"  {migration.version:>4}  {mark:<8} {migration.description}")
    outstanding = sum(1 for m in catalogue if m.version not in done)
    print(f"\n{outstanding} pending")
    return 0


async def _apply() -> int:
    ran = await migrations.run(database())
    for migration in ran:
        print(f"applied {migration.version}: {migration.description}")
    print(f"{len(ran)} migration(s) applied")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--status", action="store_true", help="list without applying")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    return asyncio.run(_status() if args.status else _apply())


if __name__ == "__main__":
    raise SystemExit(main())
