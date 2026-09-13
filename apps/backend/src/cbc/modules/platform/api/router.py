"""Aggregate platform HTTP routers."""
from __future__ import annotations

from fastapi import APIRouter

from cbc.modules.platform.api.routes import projects
from cbc.modules.platform.api.routes import jobs
from cbc.modules.platform.api.routes import terminal
from cbc.modules.platform.api.routes import settings
from cbc.modules.platform.api.routes import calls
from cbc.modules.platform.api.routes import orchestrate

router = APIRouter()
router.include_router(projects.router)
router.include_router(jobs.router)
router.include_router(terminal.router)
router.include_router(settings.router)
router.include_router(calls.router)
router.include_router(orchestrate.router)
