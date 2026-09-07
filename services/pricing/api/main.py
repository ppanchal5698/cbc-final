"""CBC Pricing API service.

Everything shared with the other five domain services lives in
`cbc.http.service_app`. What is left here is what makes this service itself:
its name, its title, and the routers it mounts.
"""
from __future__ import annotations

from cbc.http.service_app import create_service_app

from api.routers import reference_data

app = create_service_app(
    name="pricing",
    title="CBC Pricing API",
    routers=(
        reference_data.router,
    ),
)
