"""CBC Extraction API service API."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from cbc.core import envfile, logs
from cbc.services.provider import MANAGED

envfile.apply_to_environ(skip=MANAGED)

from cbc.config import settings
from cbc.db import ensure_indexes, ensure_readonly_user
from cbc.pageindex import store as pageindex_store
from cbc.http.deps import InternalAuthMiddleware
from cbc.http.tracing import TraceMiddleware
from api.routers import line_items
from api.routers import alternates

log = logs.configure("cbc.extraction.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from cbc.http import otel

    otel.configure("cbc.extraction.api")
    await ensure_indexes()
    await pageindex_store.ensure_indexes()
    if not await ensure_readonly_user():
        log.warning("no read-only MongoDB user for catalog page index")
    log.info("extraction api ready; storage at %s", settings.storage_root)
    sweep_task = None
    try:
        yield
    finally:
        pass


app = FastAPI(
    title="CBC Extraction API",
    version="0.1.0",
    lifespan=lifespan,
)

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


for router in (line_items.router,
    alternates.router,):
    app.include_router(router)


@app.get("/api/health")
async def health() -> dict:
    import asyncio
    from cbc.db import db

    try:
        await asyncio.wait_for(db.projects.database.command("ping"), timeout=3.0)
        database = "up"
    except Exception as exc:
        database = f"down: {exc}"
    return {
        "status": "ok" if database == "up" else "degraded",
        "service": "extraction",
        "database": database,
        "storageRoot": str(settings.storage_root),
        "sends": "disabled by design (NFR-1)",
    }
