"""/lite-kit under /api/reference - lite-kit list prices.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from cbc.modules.ops.api import audit
from cbc.modules.pricing.api import reference_library as reflib
from cbc.modules.pricing.domain.reference_updates import LiteKitReplace
from cbc.modules.pricing.infrastructure.reference_io import audit_family, run_sync
from cbc.shared.auth import Actor, AdminActor

router = APIRouter(prefix="/api/reference", tags=["reference"])


@router.get("/lite-kit")
async def get_lite_kit(actor: Actor) -> dict[str, Any]:
    try:
        payload = await run_sync(reflib.load_lite_kit_prices)
    except (FileNotFoundError, KeyError, OSError) as exc:
        raise HTTPException(404, "lite-kit prices data is missing") from exc
    tables = payload.get("tables") or []
    return {
        "tableCount": len(tables),
        "tables": [
            {
                "index": i,
                "pdf_page": t.get("pdf_page"),
                "title": t.get("title") or t.get("name"),
                "widthCount": len(t.get("widths") or []),
                "heightCount": len(t.get("prices") or {}),
            }
            for i, t in enumerate(tables)
        ],
        "data": payload,
    }


@router.put("/lite-kit")
async def put_lite_kit(body: LiteKitReplace, actor: AdminActor) -> dict[str, Any]:
    after = await run_sync(reflib.update_lite_kit_prices, body.data)
    await audit.record(
        "reference.lite_kit.update",
        actor,
        audit_family("lite_kit_prices"),
        after={"tableCount": len(after.get("tables") or [])},
    )
    return after


@router.patch("/lite-kit")
async def patch_lite_kit(body: LiteKitReplace, actor: AdminActor) -> dict[str, Any]:
    """Replace the document (same as PUT) — structured cell UI can deepen later."""
    after = await run_sync(reflib.update_lite_kit_prices, body.data)
    await audit.record(
        "reference.lite_kit.update",
        actor,
        audit_family("lite_kit_prices"),
        after={"tableCount": len(after.get("tables") or [])},
    )
    return after
