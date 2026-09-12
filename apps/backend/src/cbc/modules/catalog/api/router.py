"""Aggregate catalog HTTP routers."""
from __future__ import annotations

from fastapi import APIRouter

from cbc.modules.catalog.api.routes import catalog
from cbc.modules.catalog.api.routes import price_books

router = APIRouter()
router.include_router(catalog.router)
router.include_router(price_books.router)
