"""CBC Catalog API service.

The one thing this service adds to the shared application is a health field: a
database that answers `ping` says nothing about whether a part can actually be
found, and only the catalog service can answer that.
"""
from __future__ import annotations

from typing import Any

from cbc.http.service_app import create_service_app

from api.routers import catalog
from api.routers import price_books


async def _catalog_index() -> dict[str, Any]:
    from cbc.services import catalog_search

    return {
        "catalogIndex": "ready" if await catalog_search.index_available() else "missing"
    }


app = create_service_app(
    name="catalog",
    title="CBC Catalog API",
    routers=(
        catalog.router,
        price_books.router,
    ),
    health_extra=_catalog_index,
)
