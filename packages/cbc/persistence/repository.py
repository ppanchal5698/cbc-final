"""The data-access layer the specification requires by name.

§4.1, on multi-tenancy: *"the data-access layer must inject `orgId` into every
query. No collection has an index that omits it except the two text/`_id` cases
noted in §5."*

There was no such layer. Collection handles were used directly at roughly 160
call sites, each free to forget the tenant filter, the audit envelope, or the
soft-delete predicate - and all 160 did, because none of those fields existed.

A `Repository` is a thin wrapper over one motor collection that cannot forget:

  * every filter gains `orgId`
  * every insert gains the §4.2 envelope
  * every update gains `updatedAt` / `updatedBy`
  * a soft-deleted collection (§4.3) also gains `isDeleted: {$ne: true}`, and
    `delete()` marks rather than removes

It is deliberately not an ORM and not a query builder. Motor's API is good; the
only thing wrong with calling it directly was that the caller had to remember
four rules on every line. Anything the wrapper does not cover is reached through
`.collection`, which is honest about dropping the guarantees rather than growing
a method per query shape.

Converting the existing call sites is incremental: each one is a small,
verifiable diff, and a half-converted collection is still correct because the
fields the repository writes are the fields migration m002 backfilled.
"""
from __future__ import annotations

from typing import Any

from cbc.persistence import envelope


class Repository:
    """One collection, with the tenant filter and the envelope applied for you."""

    def __init__(self, collection, *, org_id: Any, actor_id: Any = None) -> None:
        self.collection = collection
        self.org_id = org_id
        self.actor_id = actor_id

    @property
    def name(self) -> str:
        return self.collection.name

    @property
    def soft_deleted(self) -> bool:
        return self.name in envelope.SOFT_DELETED

    def as_actor(self, actor_id: Any) -> "Repository":
        """The same collection, attributing writes to someone else."""
        return Repository(self.collection, org_id=self.org_id, actor_id=actor_id)

    # ── reads ───────────────────────────────────────────────────────────────

    def scope(self, query: dict[str, Any] | None = None, *, deleted: bool = False) -> dict[str, Any]:
        """A caller's filter, with the tenant - and usually the living - added.

        Exposed rather than private because the escape hatch below needs it: an
        aggregate or a bulk write reached through `.collection` should still be
        able to say `repo.scope({...})` and get the same guarantees.
        """
        scoped: dict[str, Any] = {**(query or {}), "orgId": self.org_id}
        if self.soft_deleted and not deleted:
            scoped.update(envelope.alive())
        return scoped

    def find(self, query: dict[str, Any] | None = None, *args, **kwargs):
        return self.collection.find(self.scope(query), *args, **kwargs)

    async def find_one(self, query: dict[str, Any] | None = None, *args, **kwargs):
        return await self.collection.find_one(self.scope(query), *args, **kwargs)

    async def count(self, query: dict[str, Any] | None = None) -> int:
        return await self.collection.count_documents(self.scope(query))

    async def exists(self, query: dict[str, Any] | None = None) -> bool:
        return await self.collection.find_one(self.scope(query), {"_id": 1}) is not None

    # ── writes ──────────────────────────────────────────────────────────────

    async def insert(self, document: dict[str, Any]):
        return await self.collection.insert_one(
            envelope.stamp_new(document, org_id=self.org_id, actor_id=self.actor_id)
        )

    async def insert_many(self, documents: list[dict[str, Any]]):
        if not documents:
            return None
        return await self.collection.insert_many([
            envelope.stamp_new(document, org_id=self.org_id, actor_id=self.actor_id)
            for document in documents
        ])

    async def update(self, query: dict[str, Any], changes: dict[str, Any], **kwargs):
        """`changes` are the `$set` fields; the envelope is added for you."""
        return await self.collection.update_one(
            self.scope(query),
            {"$set": envelope.stamp_update(changes, actor_id=self.actor_id)},
            **kwargs,
        )

    async def update_many(self, query: dict[str, Any], changes: dict[str, Any], **kwargs):
        return await self.collection.update_many(
            self.scope(query),
            {"$set": envelope.stamp_update(changes, actor_id=self.actor_id)},
            **kwargs,
        )

    async def apply(self, query: dict[str, Any], update: dict[str, Any], **kwargs):
        """A raw update document - `$inc`, `$push`, `$unset` - still scoped.

        The envelope is folded into whatever `$set` the caller brought, so an
        `$inc` does not lose its `updatedAt`.
        """
        merged = dict(update)
        merged["$set"] = envelope.stamp_update(
            dict(merged.get("$set") or {}), actor_id=self.actor_id
        )
        return await self.collection.update_one(self.scope(query), merged, **kwargs)

    async def delete(self, query: dict[str, Any]):
        """Soft on the five collections §4.3 names, hard everywhere else."""
        if self.soft_deleted:
            return await self.collection.update_one(
                self.scope(query),
                {"$set": envelope.soft_delete(actor_id=self.actor_id)},
            )
        return await self.collection.delete_one(self.scope(query))

    async def delete_many(self, query: dict[str, Any]):
        if self.soft_deleted:
            return await self.collection.update_many(
                self.scope(query),
                {"$set": envelope.soft_delete(actor_id=self.actor_id)},
            )
        return await self.collection.delete_many(self.scope(query))
