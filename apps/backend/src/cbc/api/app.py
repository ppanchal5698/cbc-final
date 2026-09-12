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


def create_app():
    """Build the monolith with all domain HTTP modules wired."""
    app = create_service_app(
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
        background=((settings_router.sweep_oauth_sessions, OAUTH_SWEEP_SECONDS),),
        version="0.10.0-monolith",
    )
    return app
