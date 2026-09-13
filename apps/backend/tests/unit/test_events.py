"""The in-process event bus, and every event carried across a module boundary."""
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


def test_deleting_a_bid_reaches_the_module_that_owns_its_quote(monkeypatch) -> None:
    """projects announces the deletion; quoting removes the quote lines, quote and proposal."""
    from fastapi import FastAPI

    from cbc.modules import quoting
    from cbc.modules.projects.api import bids
    from cbc.modules.quoting.infrastructure import collections
    from cbc.shared import events

    monkeypatch.setattr(events, "_subscribers", {})
    deleted: list[str] = []

    async def delete_for_project(project_id):
        deleted.append(project_id)

    monkeypatch.setattr(collections, "delete_for_project", delete_for_project)
    quoting.register(FastAPI())
    asyncio.run(events.publish(bids.PROJECT_DELETED, project_id="p1"))

    assert deleted == ["p1"]


def test_a_version_snapshot_reaches_the_modules_that_own_its_lines(monkeypatch) -> None:
    """intake announces the version; extraction and quoting each stamp their own live rows."""
    from fastapi import FastAPI

    from cbc.modules import extraction, quoting
    from cbc.modules.extraction.api import openings
    from cbc.modules.quoting.api import lines
    from cbc.shared import events

    monkeypatch.setattr(events, "_subscribers", {})
    stamped: list[tuple] = []

    async def stamp_openings(project_id, version_id):
        stamped.append(("openings", project_id, version_id))

    async def stamp_lines(project_id, version_id):
        stamped.append(("lines", project_id, version_id))

    monkeypatch.setattr(openings, "set_version", stamp_openings)
    monkeypatch.setattr(lines, "set_version", stamp_lines)
    extraction.register(FastAPI())
    quoting.register(FastAPI())
    asyncio.run(events.publish(events.VERSION_SNAPSHOT_REQUESTED, project_id="p1", version_id="v2"))

    assert stamped == [("openings", "p1", "v2"), ("lines", "p1", "v2")]


def test_confirming_openings_drops_the_quote_totals_cache(monkeypatch) -> None:
    """extraction announces confirmed openings; quoting's next totals read recomputes."""
    from fastapi import FastAPI

    from cbc.modules import quoting
    from cbc.modules.extraction.api.openings import LINES_CONFIRMED
    from cbc.modules.quoting.api import quote
    from cbc.shared import events

    monkeypatch.setattr(events, "_subscribers", {})
    monkeypatch.setitem(quote._totals_cache, "p1", (0.0, {}, []))
    quoting.register(FastAPI())
    asyncio.run(events.publish(LINES_CONFIRMED, project_id="p1", count=3))

    assert "p1" not in quote._totals_cache


def test_a_completed_quote_ends_the_saga_in_the_api_and_in_the_worker(monkeypatch) -> None:
    """quoting announces the drafted proposal; projects ends the saga at complete and the stage at 100.

    The worker mounts no routes, so `projects.subscribe` must work on its own - a
    build_proposal pass would otherwise leave the bid short of complete.
    """
    from fastapi import FastAPI

    from cbc.modules import projects
    from cbc.modules.projects.api import bids, saga
    from cbc.shared import events

    moved: list[tuple] = []

    async def set_state(project_id, state, *, detail=None):
        moved.append(("state", project_id, state))

    async def set_stage(project_id, stage, progress, *, phase=None):
        moved.append(("stage", project_id, stage, progress))

    monkeypatch.setattr(saga, "set_state", set_state)
    monkeypatch.setattr(bids, "set_stage", set_stage)
    for compose in (lambda: projects.register(FastAPI()), projects.subscribe):
        monkeypatch.setattr(events, "_subscribers", {})
        compose()
        asyncio.run(events.publish(events.QUOTE_COMPLETED, project_id="p1"))

    assert moved == [("state", "p1", "complete"), ("stage", "p1", "proposal", 100)] * 2
