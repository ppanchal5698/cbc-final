"""Shared FastAPI dependencies."""
from __future__ import annotations

import secrets as pysecrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from cbc.config import settings
from cbc.http import service_jwt

# Endpoints that must stay reachable without the internal service token.
PUBLIC_PATHS = frozenset({"/api/health", "/api/auth/verify"})


def get_actor(request: Request) -> str:
    """Return the authenticated actor set by InternalAuthMiddleware."""
    return getattr(request.state, "actor", "estimator")


Actor = Annotated[str, Depends(get_actor)]

# Who may reach provider credentials and the destructive routes. The role is read
# from the database, not from a header: the internal token authenticates the
# Next.js server, not the person behind it, so trusting a caller-supplied role
# would make every signed-in estimator an administrator.
ADMIN_ROLES = frozenset({"admin"})


async def require_admin(request: Request) -> str:
    from cbc.db import db

    actor = get_actor(request)
    user = await db.users.find_one({"email": actor.lower()}, {"role": 1})
    if not user or user.get("role") not in ADMIN_ROLES:
        raise HTTPException(
            403,
            f"{actor} is not permitted here. This needs one of: "
            + ", ".join(sorted(ADMIN_ROLES)),
        )
    return actor


AdminActor = Annotated[str, Depends(require_admin)]


def _unauthorized(detail: str = "Unauthorized") -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": detail})


class InternalAuthMiddleware(BaseHTTPMiddleware):
    """Authenticate the Next.js server on every /api route except the public set.

    INTERNAL_AUTH=token (default for pytest): shared X-Internal-Token + X-Actor.
    INTERNAL_AUTH=jwt: Authorization Bearer with aud matching SERVICE_AUDIENCE;
    the signed-in email is JWT `sub` (X-Actor is ignored so it cannot be forged).
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path
        if not path.startswith("/api/") or path in PUBLIC_PATHS:
            return await call_next(request)

        mode = service_jwt.auth_mode()
        if mode == "jwt":
            return await self._dispatch_jwt(request, call_next)
        return await self._dispatch_token(request, call_next)

    async def _dispatch_token(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # No `if token:` guard. An empty INTERNAL_API_TOKEN used to skip this
        # comparison, which authenticated every caller that sent an X-Actor
        # header - in any environment, with nothing in the logs to say so.
        token = settings.internal_api_token
        provided = request.headers.get("X-Internal-Token", "")
        if not token or not pysecrets.compare_digest(provided, token):
            return _unauthorized()

        actor = request.headers.get("X-Actor", "").strip()
        if not actor:
            return _unauthorized("X-Actor header required")
        request.state.actor = actor
        return await call_next(request)

    async def _dispatch_jwt(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        auth = request.headers.get("Authorization", "")
        if not auth.lower().startswith("bearer "):
            return _unauthorized("Bearer token required")
        raw = auth[7:].strip()
        if not raw:
            return _unauthorized("Bearer token required")
        try:
            claims = service_jwt.verify(raw)
        except Exception:
            return _unauthorized("invalid or expired service token")
        actor = str(claims.get("sub") or claims.get("actor") or "").strip()
        if not actor:
            return _unauthorized("token subject missing")
        request.state.actor = actor
        return await call_next(request)
