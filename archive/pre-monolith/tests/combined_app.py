"""Combined FastAPI app for integration tests.

Production runs split domain services. Tests exercise the full HTTP surface
against one process that mounts every domain router, with the same auth and
shared `cbc` package.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parents[1]
for service in (
    "platform",
    "intake",
    "extraction",
    "pricing",
    "quoting",
    "catalog",
):
    path = ROOT / "services" / service
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from cbc.config import settings
from cbc.http.deps import InternalAuthMiddleware

# Import after path setup — each service package is named `api`.
# Load routers by file path to avoid package-name collisions.
import importlib.util


def _load_router(service: str, module: str):
    file = ROOT / "services" / service / "api" / "routers" / f"{module}.py"
    spec = importlib.util.spec_from_file_location(
        f"cbc_test.{service}.{module}", file
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Provide a fake api.routers package for intra-service imports
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod.router


app = FastAPI(title="CBC Combined Test API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(InternalAuthMiddleware)


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# Prefer importing via temporarily switching sys.path + import api.routers
# for each service in isolation.

def _include_service(service: str, modules: list[str]) -> None:
    service_root = str(ROOT / "services" / service)
    # Put this service first so `import api` resolves to it
    while service_root in sys.path:
        sys.path.remove(service_root)
    sys.path.insert(0, service_root)
    # Drop cached api modules from a previous service
    doomed = [k for k in list(sys.modules) if k == "api" or k.startswith("api.")]
    for k in doomed:
        del sys.modules[k]
    for name in modules:
        mod = __import__(f"api.routers.{name}", fromlist=["router"])
        app.include_router(mod.router)


_include_service(
    "platform",
    [
        "auth",
        "users",
        "audit_log",
        "projects",
        "jobs",
        "terminal",
        "settings",
        "calls",
        "integrations",
        "orchestrate",
    ],
)
_include_service("intake", ["versions", "documents"])
_include_service("extraction", ["line_items", "alternates"])
_include_service("pricing", ["reference_data"])
_include_service("quoting", ["quote", "proposal"])
_include_service("catalog", ["catalog", "price_books"])


@app.get("/api/health")
async def health() -> dict:
    """The same payload the real services return.

    This used to be a two-key stub, so every assertion about health passed
    against something no service actually serves.
    """
    import asyncio

    from cbc.db import db
    from cbc.services import catalog_search

    try:
        await asyncio.wait_for(db.projects.database.command("ping"), timeout=3.0)
        database = "up"
    except Exception as exc:
        database = f"down: {exc}"
    return {
        "status": "ok" if database == "up" else "degraded",
        "service": "combined-test",
        "database": database,
        "storageRoot": str(settings.storage_root),
        "catalogIndex": "ready" if await catalog_search.index_available() else "missing",
        "sends": "disabled by design (NFR-1)",
    }
