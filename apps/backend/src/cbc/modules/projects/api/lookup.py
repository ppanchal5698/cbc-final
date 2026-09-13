"""Finding a bid by code (CBC-260143), slug or id - whatever the caller has.

Every module's routes start here. A miss raises ProjectNotFound, which the
composition root turns into the 404 this lookup has always returned.
"""
from __future__ import annotations

from typing import Any, TypedDict

from cbc.modules.projects.infrastructure.collections import bid_requests
from cbc.shared.mongo import oid


class ProjectNotFound(LookupError):
    """No bid matches the code, slug or id asked for."""

    def __init__(self, code_or_id: str) -> None:
        super().__init__(f"project not found: {code_or_id}")


class ProjectRef(TypedDict, total=False):
    """A stored bid, as other modules read it.

    Still the stored document at runtime: a TypedDict converts nothing.
    tests/architecture/test_port_types.py fails when another module reads a field
    not named here.
    """

    _id: Any
    orgId: Any
    code: str
    slug: str
    name: str
    version: int
    autopilot: bool
    alternates: list[str]
    state: str
    location: str
    gc: str
    architect: str
    initiator: str
    degraded: bool
    producedBy: str
    hasTrustDialogAccepted: bool


async def load(code_or_id: str) -> ProjectRef:
    """Look a project up by code (CBC-260143), slug, or id - whatever the caller has."""
    query: dict[str, Any] = {"$or": [{"code": code_or_id}, {"slug": code_or_id}]}
    try:
        query["$or"].append({"_id": oid(code_or_id)})
    except ValueError:
        pass
    project = await bid_requests().find_one(query)
    if not project:
        raise ProjectNotFound(code_or_id)
    return project


async def get(project_id: Any) -> ProjectRef | None:
    """The stored bid with this id, or None - for a job, which carries the id already."""
    return await bid_requests().find_one({"_id": project_id})


async def project_id(code_or_id: str) -> Any:
    return (await load(code_or_id))["_id"]


async def summaries(project_ids: list[Any]) -> dict[Any, dict[str, Any]]:
    """Code, name and slug for each of these bid ids, keyed by id."""
    cursor = bid_requests().find({"_id": {"$in": project_ids}}, {"code": 1, "name": 1, "slug": 1})
    return {project["_id"]: project async for project in cursor}
