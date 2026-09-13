"""The in-process event bus, and the one event carried across a module boundary today."""
from __future__ import annotations

import asyncio


def test_each_subscriber_runs_once_in_the_order_it_subscribed(monkeypatch) -> None:
    from cbc.shared import events

    monkeypatch.setattr(events, "_subscribers", {})
    heard: list[tuple[str, int]] = []

    async def first(n: int) -> None:
        heard.append(("first", n))

    async def second(n: int) -> None:
        heard.append(("second", n))

    events.subscribe("t", first)
    events.subscribe("t", second)
    events.subscribe("t", first)  # composed twice: must not run twice
    asyncio.run(events.publish("t", n=1))
    asyncio.run(events.publish("nobody-listens", n=2))

    assert heard == [("first", 1), ("second", 1)]


def test_a_retried_job_returns_its_bid_to_that_jobs_starting_state(monkeypatch) -> None:
    """ops publishes; projects moves the saga. Composing the app wires the two."""
    from fastapi import FastAPI

    from cbc.modules import projects
    from cbc.modules.ops.api import jobs
    from cbc.modules.projects.api import saga
    from cbc.shared import events

    monkeypatch.setattr(events, "_subscribers", {})
    moved: list[tuple] = []

    async def set_state(project_id, state, *, detail=None):
        moved.append((project_id, state, detail))

    monkeypatch.setattr(saga, "set_state", set_state)
    projects.register(FastAPI())

    asyncio.run(events.publish(jobs.JOB_REQUEUED, job={"type": "match_and_price", "projectId": "p1"}))
    asyncio.run(events.publish(jobs.JOB_REQUEUED, job={"type": "index_catalog", "projectId": None}))

    assert moved == [("p1", "pricing", "Requeued from the dead-letter queue.")]


def test_deleting_a_bid_reaches_the_module_that_owns_its_documents(monkeypatch) -> None:
    """projects announces the deletion; intake removes its documents and versions."""
    from fastapi import FastAPI

    from cbc.modules import intake
    from cbc.modules.intake.infrastructure import collections
    from cbc.modules.projects.api import bids
    from cbc.shared import events

    monkeypatch.setattr(events, "_subscribers", {})
    deleted: list[str] = []

    async def delete_for_project(project_id):
        deleted.append(project_id)

    monkeypatch.setattr(collections, "delete_for_project", delete_for_project)
    intake.register(FastAPI())
    asyncio.run(events.publish(bids.PROJECT_DELETED, project_id="p1"))

    assert deleted == ["p1"]


def test_deleting_a_bid_reaches_the_module_that_owns_its_openings(monkeypatch) -> None:
    """projects announces the deletion; extraction removes the bid's openings."""
    from fastapi import FastAPI

    from cbc.modules import extraction
    from cbc.modules.extraction.infrastructure import collections
    from cbc.modules.projects.api import bids
    from cbc.shared import events

    monkeypatch.setattr(events, "_subscribers", {})
    deleted: list[str] = []

    async def delete_for_project(project_id):
        deleted.append(project_id)

    monkeypatch.setattr(collections, "delete_for_project", delete_for_project)
    extraction.register(FastAPI())
    asyncio.run(events.publish(bids.PROJECT_DELETED, project_id="p1"))

    assert deleted == ["p1"]
