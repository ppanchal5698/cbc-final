"""FastAPI application factory for the modular monolith (Platform live)."""
from __future__ import annotations

from cbc.http.service_app import create_service_app
from cbc.modules.platform.api.routes import settings as settings_router
from cbc.modules.platform.api.router import router as platform_router
from cbc.modules.catalog.api.router import router as catalog_router
from cbc.modules.extraction.api.router import router as extraction_router
from cbc.modules.intake.api.router import router as intake_router
from cbc.modules.pricing.api.router import router as pricing_router
from cbc.modules.quoting.api.router import router as quoting_router

OAUTH_SWEEP_SECONDS = 60
VERSION = "0.10.0-monolith"


def create_app(*, background: bool = True):
    """Build the monolith with all domain HTTP modules wired.

    `background=False` omits the OAuth session sweep, which is the only periodic
    task in the process. The test harness needs that, and used to get it by
    re-implementing this function - a copy that drifted to version "0.9.1-monolith"
    while this one said "0.10.0", and that the version smoke test could not catch
    because it only looked for the substring "monolith".
    """
    jobs = ()
    if background:
        jobs = ((settings_router.sweep_oauth_sessions, OAUTH_SWEEP_SECONDS),)

    return create_service_app(
        name="platform",
        title="CBC Estimating Copilot API",
        routers=(
            platform_router,
            intake_router,
            extraction_router,
            pricing_router,
            quoting_router,
            catalog_router,
        ),
        background=jobs,
        version=VERSION,
    )
