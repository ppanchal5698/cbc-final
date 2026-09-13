"""One FastAPI application, configured six ways.

`services/{platform,intake,extraction,pricing,quoting,catalog}/api/main.py` were
near-copies: 123, 88, 88, 86, 88 and 92 lines, differing by 18-24 lines each, and
every difference a name string or a router tuple. `value_error_handler` was
byte-identical in seven files (the six services plus the test harness), `health`
in seven, `lifespan` in all six.

Copy-paste residue came with them: a module-level `import asyncio` nothing used,
because each `health()` re-imports it locally, and a `sweep_task = None` followed
by `try: yield / finally: pass` in the five services that have no sweep - the
vestige of the one service that does.

What actually differs between services is three things: what it is called, which
routers it mounts, and whether it has any background work. Those are the
parameters here.

The import order at the top of this module is load-bearing. `envfile` writes the
`.env` into `os.environ`, and `cbc.shared.config.settings` reads `os.environ` once at
import. Applying the file after settings are built produces a service that
silently ignores its own configuration, which is why every main.py had these two
lines in this order before importing anything else. Doing it here means six files
cannot get it wrong.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable, Sequence
from contextlib import asynccontextmanager
from typing import Any

from cbc.shared import envfile, logs
from cbc.services.provider import MANAGED

envfile.apply_to_environ(skip=MANAGED)

from cbc.shared.config import settings  # noqa: E402  - must follow apply_to_environ
from cbc.db import ensure_indexes, ensure_readonly_user  # noqa: E402
from cbc.shared.auth import InternalAuthMiddleware  # noqa: E402
from cbc.shared.tracing import TraceMiddleware  # noqa: E402
from cbc.pageindex import store as pageindex_store  # noqa: E402

# A background job that runs for the life of the service: an async callable and
# how often to re-run it.
BackgroundJob = tuple[Callable[[], Awaitable[Any]], float]

HealthExtra = Callable[[], Awaitable[dict[str, Any]]]


async def _health(name: str, extra: HealthExtra | None) -> dict[str, Any]:
    from cbc.db import db

    try:
        # `db.projects` resolves to the bidRequests collection; the accessor
        # keeps the name the code has always spelled (see persistence.names).
        await asyncio.wait_for(db.projects.database.command("ping"), timeout=3.0)
        database = "up"
    except Exception as exc:  # surfaced, not swallowed - the UI shows this
        database = f"down: {exc}"

    payload = {
        "status": "ok" if database == "up" else "degraded",
        "service": name,
        "database": database,
        "storageRoot": str(settings.storage_root),
        "sends": "disabled by design (NFR-1)",
    }
    if extra is not None:
        try:
            payload.update(await extra())
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


def create_service_app(
    *,
    name: str,
    title: str,
    routers: Sequence[Any] = (),
    background: Iterable[BackgroundJob] = (),
    health_extra: HealthExtra | None = None,
    version: str = "0.1.0",
):
    """Build one domain service.

    `name` is the short domain word - "intake", "quoting" - and is used for the
    logger, the trace service name and the `service` field in health, which were
    three separately-typed strings per service before.
    """
    from fastapi import FastAPI, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse

    log = logs.configure(f"cbc.{name}.api")
    jobs = list(background)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from cbc.shared import otel

        otel.configure(f"cbc.{name}.api")
        await ensure_indexes()
        await pageindex_store.ensure_indexes()
        if not await ensure_readonly_user():
            log.warning("no read-only MongoDB user for catalog page index")
        log.info("%s api ready; storage at %s", name, settings.storage_root)

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

    app = FastAPI(title=title, version=version, lifespan=lifespan)

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

    for router in routers:
        app.include_router(router)

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return await _health(name, health_extra)

    return app
