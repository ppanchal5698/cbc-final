"""Aggregate pricing HTTP routers."""
from __future__ import annotations

from fastapi import APIRouter

from cbc.modules.pricing.api.routes import reference_data

router = APIRouter()
router.include_router(reference_data.router)
