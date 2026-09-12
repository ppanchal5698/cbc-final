"""Aggregate quoting HTTP routers."""
from __future__ import annotations

from fastapi import APIRouter

from cbc.modules.quoting.api.routes import quote
from cbc.modules.quoting.api.routes import proposal
from cbc.modules.quoting.api.routes import operational

router = APIRouter()
router.include_router(quote.router)
router.include_router(proposal.router)
router.include_router(operational.router)
