"""CBC Platform API service.

The widest of the six - auth, users, projects, jobs, settings and ops - and the
only one with background work: expired Claude OAuth sign-in sessions are swept
once a minute, because a browser flow that is abandoned half-way leaves a row
behind that nothing else will ever clean up.
"""
from __future__ import annotations

from cbc.http.service_app import create_service_app

from api.routers import audit_log
from api.routers import auth
from api.routers import calls
from api.routers import integrations
from api.routers import jobs
from api.routers import ops
from api.routers import orchestrate
from api.routers import projects
from api.routers import settings as settings_router
from api.routers import terminal
from api.routers import users

OAUTH_SWEEP_SECONDS = 60


app = create_service_app(
    name="platform",
    title="CBC Platform API",
    routers=(
        auth.router,
        users.router,
        audit_log.router,
        projects.router,
        jobs.router,
        terminal.router,
        settings_router.router,
        calls.router,
        integrations.router,
        orchestrate.router,
        ops.router,
    ),
    background=((settings_router.sweep_oauth_sessions, OAUTH_SWEEP_SECONDS),),
)
