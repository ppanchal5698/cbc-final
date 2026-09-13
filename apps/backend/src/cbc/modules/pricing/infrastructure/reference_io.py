"""Reference data is read and written synchronously; the routes hop threads to reach it.
"""
from __future__ import annotations

import asyncio


async def run_sync(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


def audit_family(family: str) -> dict[str, str]:
    return {"family": family, "collection": "referenceData"}
