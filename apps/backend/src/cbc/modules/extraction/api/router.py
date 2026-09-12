"""Aggregate extraction HTTP routers."""
from __future__ import annotations

from fastapi import APIRouter

from cbc.modules.extraction.api.routes import line_items
from cbc.modules.extraction.api.routes import alternates

router = APIRouter()
router.include_router(line_items.router)
router.include_router(alternates.router)
