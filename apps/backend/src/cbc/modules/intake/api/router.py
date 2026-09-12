"""Aggregate intake HTTP routers."""
from __future__ import annotations

from fastapi import APIRouter

# versions before documents: documents imports snapshot from versions
from cbc.modules.intake.api.routes import versions
from cbc.modules.intake.api.routes import documents

router = APIRouter()
router.include_router(documents.router)
router.include_router(versions.router)
