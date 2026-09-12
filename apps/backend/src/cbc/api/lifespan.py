"""Application lifespan stub (indexes / background jobs later)."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
