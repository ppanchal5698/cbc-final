"""The Neo4j connection the memory curator writes through and recall reads through.

The graph is optional. With NEO4J_URI unset, or the server down, `configured()`
or `reachable()` says so and every caller carries on without it: a bid prices
the same with or without its memory, it just prices with less help.
"""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger("cbc.memory")

# Every node label carries a `key`, unique within its label, so a sync is a set of
# MERGEs and running it twice changes nothing.
LABELS = (
    "Vendor",
    "Multiplier",
    "PriceBook",
    "CatalogItem",
    "Customer",
    "Architect",
    "ReferenceFamily",
    "FrameDepth",
    "FrpConstant",
    "Finish",
    "TaxRate",
    "SpecialNet",
    "MarginBand",
    "Division",
    "Section",
    "SpecItem",
    "Bid",
    "HardwareSet",
    "WorkflowStep",
    "Finding",
    "Insight",
)

_driver: Any = None


def configured() -> bool:
    return bool(os.environ.get("NEO4J_URI", "").strip())


def _database() -> str:
    return os.environ.get("NEO4J_DATABASE", "").strip() or "neo4j"


def driver() -> Any:
    """One async driver per process. The driver pools its own connections."""
    global _driver
    if _driver is None:
        from neo4j import AsyncGraphDatabase

        _driver = AsyncGraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(os.environ.get("NEO4J_USER", "neo4j"), os.environ.get("NEO4J_PASSWORD", "")),
            connection_timeout=5,
            # "That property is not in the database yet" on every read of a field
            # no node has had - a dismissal, an explanation - is noise, not news.
            notifications_disabled_categories=["UNRECOGNIZED"],
        )
    return _driver


async def close() -> None:
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None


async def reachable() -> bool:
    if not configured():
        return False
    try:
        await driver().verify_connectivity()
        return True
    except Exception as exc:  # the graph is optional; say why it is unavailable and move on
        log.warning("memory graph unreachable: %s", exc)
        return False


async def write(query: str, **params: Any) -> list[dict[str, Any]]:
    """Run a write; the rows it RETURNs, if any."""
    result = await driver().execute_query(query, params, database_=_database())
    return [record.data() for record in result.records]


async def read(query: str, **params: Any) -> list[dict[str, Any]]:
    from neo4j import RoutingControl

    result = await driver().execute_query(
        query, params, database_=_database(), routing_=RoutingControl.READ
    )
    return [record.data() for record in result.records]


async def ensure_schema() -> None:
    """One uniqueness constraint per label - which also gives every `key` an index."""
    for label in LABELS:
        await write(
            f"CREATE CONSTRAINT {label.lower()}_key IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.key IS UNIQUE"
        )
