"""GET /api/settings/ollama/models - models on a host Ollama, for the model picker."""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from cbc.modules.ops.api import provider
from cbc.shared.auth import require_admin

# Every settings route is admin-only: they read or write provider credentials,
# spawn CLI processes, or change how every bid behaves.
router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_admin)])


@router.get("/ollama/models")
async def list_ollama_models(
    baseUrl: str | None = Query(default=None),
) -> dict[str, Any]:
    """Return models from a host Ollama instance for the settings model picker."""
    import httpx

    resolved = baseUrl or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    try:
        provider.check_base_url(resolved)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    url = resolved.rstrip("/") + "/api/tags"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(
            502,
            f"Could not reach Ollama at {resolved!r}: {exc}",
        ) from exc

    models = []
    for entry in payload.get("models") or []:
        models.append(
            {
                "name": entry.get("name"),
                "size": entry.get("size"),
                "modifiedAt": entry.get("modified_at"),
            }
        )
    return {"baseUrl": resolved, "models": models}
