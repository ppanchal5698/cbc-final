"""Forward-only, idempotent, versioned database migrations.

There were none. `ensure_indexes()` is idempotent index setup and nothing else,
so any change to the shape of stored data - renaming a collection to the name the
specification gives it, adding the `orgId` every document is required to carry -
had no mechanism behind it but a hand-run script and hope. `db.py` even tells an
operator at runtime to run `scripts/dedupe_products.py`, which does not exist.

A migration here is a module in this package with three names:

    VERSION      int, unique, applied in ascending order
    DESCRIPTION  one line, shown when it runs
    apply(db)    async, idempotent - running it twice must be harmless

Applied versions are recorded in `schemaMigrations`, one document per version,
so a restart or a second API container re-running startup is a no-op. There is
no `down()`: rolling a database backwards on an estimating desk loses quotes, and
the honest alternative is a new forward migration that undoes the change.

    python -m cbc.persistence.migrations          # apply what is pending
    python -m cbc.persistence.migrations --status # say what would run
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import logging
import pkgutil
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

LEDGER = "schemaMigrations"

log = logging.getLogger("cbc.migrations")


@dataclass(frozen=True)
class Migration:
    version: int
    description: str
    apply: Callable[[Any], Coroutine[Any, Any, Any]]
    module: str


def discover() -> list[Migration]:
    """Every migration module in this package, in version order."""
    found: dict[int, Migration] = {}
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{__name__}.{info.name}")
        for required in ("VERSION", "DESCRIPTION", "apply"):
            if not hasattr(module, required):
                raise AttributeError(
                    f"migration {info.name} is missing {required!r}; see this "
                    "package's docstring for the three names a migration needs"
                )
        version = int(module.VERSION)
        if version in found:
            raise ValueError(
                f"two migrations claim version {version}: "
                f"{found[version].module} and {info.name}"
            )
        found[version] = Migration(
            version=version,
            description=str(module.DESCRIPTION).strip(),
            apply=module.apply,
            module=info.name,
        )
    return [found[version] for version in sorted(found)]


async def applied_versions(database) -> set[int]:
    return {
        document["_id"]
        async for document in database[LEDGER].find({}, {"_id": 1})
    }


async def pending(database) -> list[Migration]:
    done = await applied_versions(database)
    return [migration for migration in discover() if migration.version not in done]


async def run(database=None) -> list[Migration]:
    """Apply every pending migration in order. Returns the ones that ran."""
    if database is None:
        from cbc.db import database as resolve

        database = resolve()

    ran: list[Migration] = []
    for migration in await pending(database):
        log.info("migration %s: %s", migration.version, migration.description)
        await migration.apply(database)
        # Recorded only after apply() returns. A migration that raises is not
        # marked done, so the next start retries it - which is why apply() must
        # be idempotent rather than merely correct once.
        await database[LEDGER].update_one(
            {"_id": migration.version},
            {
                "$set": {
                    "description": migration.description,
                    "module": migration.module,
                    "appliedAt": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )
        ran.append(migration)
    return ran


async def _status() -> int:
    from cbc.db import database

    db = database()
    done = await applied_versions(db)
    for migration in discover():
        mark = "applied" if migration.version in done else "PENDING"
        print(f"  {migration.version:>4}  {mark:<8} {migration.description}")
    outstanding = len([m for m in discover() if m.version not in done])
    print(f"\n{outstanding} pending")
    return 0


async def _apply() -> int:
    ran = await run()
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
