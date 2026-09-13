"""The composition root: the one place the API process is assembled.

Everything that exists at process level is wired here and nowhere else - the
middleware, the error mapping, health, the lifespan that migrates and indexes the
database, the periodic work, and the routers.

This replaces two files. `http/service_app.py` built "one FastAPI application,
configured six ways", a factory kept for six domain services that are now one
process, and `api/app.py` called it with a single configuration. The six-way
parameters were vestigial; what is left is the one app.

The import order below is load-bearing. `envfile` writes `.env` into
`os.environ`, and `cbc.shared.config.settings` reads `os.environ` once, at
import. Applying the file after settings are built gives a process that silently
ignores its own configuration. tests/architecture/test_composition_root.py
checks the order rather than trusting this paragraph.

Run it with `uvicorn cbc.app.main:create_app --factory`, or the `cbc-api` script.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from cbc.shared import envfile, logs
from cbc.modules.ops.api.provider import MANAGED

envfile.apply_to_environ(skip=MANAGED)

from cbc.shared.config import settings  # noqa: E402  - must follow apply_to_environ
from cbc.db import ensure_indexes, ensure_readonly_user  # noqa: E402
from cbc.modules import catalog, extraction, intake, ops, pricing, projects  # noqa: E402
from cbc.modules.ops.api import identity, jobs as ops_jobs, project_lookup  # noqa: E402
from cbc.modules.projects.api import lookup as projects_lookup  # noqa: E402
from cbc.modules.quoting.api.router import router as quoting_router  # noqa: E402
from cbc.pageindex import store as pageindex_store  # noqa: E402
from cbc.shared.auth import InternalAuthMiddleware, set_role_lookup  # noqa: E402
from cbc.shared.mongo import database  # noqa: E402
from cbc.shared.tracing import TraceMiddleware  # noqa: E402

NAME = "platform"  # the compose service name, the log/trace name, and health's `service`
TITLE = "CBC Estimating Copilot API"
VERSION = "0.10.0-monolith"

ROUTERS = (
    quoting_router,
)


async def _catalog_index() -> dict[str, str]:
    """Whether a part can actually be found, not just whether Mongo answers ping.

    The pre-monolith catalog service added this to /api/health. The cutover
    mounted its routers but not its health field, so `catalogIndex` quietly left
    the payload until it was restored.
    """
    from cbc.modules.catalog.api import search as catalog_search

    return {"catalogIndex": "ready" if await catalog_search.index_available() else "missing"}


async def _health() -> dict[str, Any]:
    try:
        await asyncio.wait_for(database().command("ping"), timeout=3.0)
        state = "up"
    except Exception as exc:  # surfaced, not swallowed - the UI shows this
        state = f"down: {exc}"

    payload = {
        "status": "ok" if state == "up" else "degraded",
        "service": NAME,
        "database": state,
        "storageRoot": str(settings.storage_root),
        "sends": "disabled by design (NFR-1)",
    }
    try:
        payload.update(await _catalog_index())
    except Exception as exc:  # a broken extra must not take health down
        payload["extraError"] = str(exc)
    return payload


def _forever(job: Callable[[], Awaitable[Any]], every: float, log: logging.Logger):
    async def loop() -> None:
        while True:
            try:
                await job()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("%s failed", getattr(job, "__name__", "background job"))
            await asyncio.sleep(every)

    return loop


async def migrate_and_index() -> None:
    """Migrations first, then every index: the legacy set in db.py, then each module's.

    Order matters. An index built on a collection before migration 1 renames it
    lands on the wrong collection.
    """
    await ensure_indexes()
    await ops.ensure_indexes()
    await projects.ensure_indexes()
    await catalog.ensure_indexes()
    await intake.ensure_indexes()
    await extraction.ensure_indexes()
    await pricing.ensure_indexes()


def create_app(*, background: bool = True):
    """Build the API.

    `background=False` omits the OAuth session sweep, the only periodic task in
    the process. The test harness needs that; it used to get it by re-implementing
    the factory, a copy that drifted to a different version string.
    """
    from fastapi import FastAPI, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse

    log = logs.configure(f"cbc.{NAME}.api")
    jobs = ops.background_jobs() if background else []

    # Dependencies that point the other way: shared and ops each need an answer
    # they may not import. The owners are plugged in here, and only here.
    set_role_lookup(identity.role_of)
    project_lookup.bind(projects_lookup.project_id, projects_lookup.summaries)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from cbc.shared import otel

        otel.configure(f"cbc.{NAME}.api")
        await migrate_and_index()
        await pageindex_store.ensure_indexes()
        if not await ensure_readonly_user():
            log.warning("no read-only MongoDB user for catalog page index")
        log.info("%s api ready; storage at %s", NAME, settings.storage_root)

        running = [asyncio.create_task(_forever(job, every, log)()) for job, every in jobs]
        try:
            yield
        finally:
            for task in running:
                task.cancel()
            for task in running:
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

    app = FastAPI(title=TITLE, version=VERSION, lifespan=lifespan)

    # Order kept exactly as it was: Starlette runs the last-added middleware
    # outermost, so tracing wraps authentication, which wraps CORS.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(InternalAuthMiddleware)
    app.add_middleware(TraceMiddleware)

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    # Queue policy refuses with a typed error; this is where it becomes HTTP - the
    # same 409 and body the policy used to raise itself.
    @app.exception_handler(ops_jobs.PipelineJobActive)
    async def pipeline_job_active_handler(request: Request, exc: ops_jobs.PipelineJobActive) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": ops_jobs.conflict_detail(exc.active)})

    # A bid lookup that misses raises a typed error; this is its 404, with the body
    # the lookup used to raise itself.
    @app.exception_handler(projects_lookup.ProjectNotFound)
    async def project_not_found_handler(request: Request, exc: projects_lookup.ProjectNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    projects.register(app)
    intake.register(app)
    extraction.register(app)
    pricing.register(app)
    for router in ROUTERS:
        app.include_router(router)
    catalog.register(app)
    ops.register(app)

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return await _health()

    return app


def run() -> None:
    """The `cbc-api` console script."""
    import uvicorn

    uvicorn.run("cbc.app.main:create_app", factory=True, host="0.0.0.0", port=8001, reload=False)
