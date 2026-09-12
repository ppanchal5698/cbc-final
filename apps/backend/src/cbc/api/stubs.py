"""Shared stub helpers for Phase 0 route placeholders."""
from __future__ import annotations

from fastapi import APIRouter, Response, status


def not_implemented() -> Response:
    return Response(status_code=status.HTTP_501_NOT_IMPLEMENTED)


def stub_router(prefix: str, *tags: str) -> APIRouter:
    return APIRouter(prefix=prefix, tags=list(tags))
