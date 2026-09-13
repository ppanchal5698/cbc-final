"""Short-lived HS256 service JWTs between Next.js and domain APIs.

When INTERNAL_AUTH=jwt, the web proxy signs a token with aud matching the
upstream SERVICE_AUDIENCE. FastAPI verifies signature + audience and takes
the actor from the JWT subject (not a forgeable X-Actor header).
"""
from __future__ import annotations

import os
import time
from typing import Any

import jwt

ISSUER = "cbc-web"
ALG = "HS256"


def auth_mode() -> str:
    return os.environ.get("INTERNAL_AUTH", "token").strip().lower() or "token"


def service_audience() -> str:
    return os.environ.get("SERVICE_AUDIENCE", "platform").strip() or "platform"


def jwt_secrets() -> list[str]:
    """Current secret first, then previous, for rotation without downtime."""
    current = os.environ.get("INTERNAL_JWT_SECRET", "").strip()
    if not current:
        current = os.environ.get(
            "INTERNAL_API_TOKEN",
            os.environ.get("APP_SECRET_KEY", "cbc-local-dev-key-change-me"),
        ).strip()
    previous = os.environ.get("INTERNAL_JWT_SECRET_PREVIOUS", "").strip()
    secrets = [current] if current else []
    if previous and previous not in secrets:
        secrets.append(previous)
    return secrets


def mint(
    actor: str,
    audience: str,
    *,
    secret: str | None = None,
    ttl_seconds: int = 60,
    now: int | None = None,
) -> str:
    """Mint a service JWT (tests / local tooling). Production mints in Next.js."""
    issued = int(now if now is not None else time.time())
    key = secret or (jwt_secrets()[0] if jwt_secrets() else "")
    payload = {
        "sub": actor,
        "actor": actor,
        "aud": audience,
        "iss": ISSUER,
        "iat": issued,
        "exp": issued + max(15, ttl_seconds),
    }
    return jwt.encode(payload, key, algorithm=ALG)


def verify(token: str, *, audience: str | None = None) -> dict[str, Any]:
    """Return claims or raise jwt.PyJWTError / ValueError."""
    aud = audience or service_audience()
    secrets = jwt_secrets()
    if not secrets:
        raise ValueError("no INTERNAL_JWT_SECRET configured")
    last_error: Exception | None = None
    for secret in secrets:
        try:
            return jwt.decode(
                token,
                secret,
                algorithms=[ALG],
                audience=aud,
                issuer=ISSUER,
                options={"require": ["exp", "iat", "sub", "aud"]},
            )
        except jwt.PyJWTError as exc:
            last_error = exc
            continue
    assert last_error is not None
    raise last_error
