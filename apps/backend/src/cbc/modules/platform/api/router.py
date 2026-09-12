"""Aggregate platform HTTP routers."""
from __future__ import annotations

from fastapi import APIRouter

from cbc.modules.platform.api.routes import auth
from cbc.modules.platform.api.routes import users
from cbc.modules.platform.api.routes import projects
from cbc.modules.platform.api.routes import jobs
from cbc.modules.platform.api.routes import terminal
from cbc.modules.platform.api.routes import settings
from cbc.modules.platform.api.routes import calls
from cbc.modules.platform.api.routes import integrations
from cbc.modules.platform.api.routes import orchestrate
from cbc.modules.platform.api.routes import ops
from cbc.modules.platform.api.routes import audit_log

router = APIRouter()
router.include_router(auth.router)
router.include_router(users.router)
router.include_router(projects.router)
router.include_router(jobs.router)
router.include_router(terminal.router)
router.include_router(settings.router)
router.include_router(calls.router)
router.include_router(integrations.router)
router.include_router(orchestrate.router)
router.include_router(ops.router)
router.include_router(audit_log.router)
