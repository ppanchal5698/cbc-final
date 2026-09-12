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

    python scripts/migrate.py            # apply what is pending
    python scripts/migrate.py --status   # say what would run
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


async def run(database) -> list[Migration]:
    """Apply every pending migration in order. Returns the ones that ran.

    The database is handed in. This package is below `cbc.db` in the dependency
    order and must not reach up for a client - `scripts/migrate.py` is the
    operator entry point that knows how to make one.
    """
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
