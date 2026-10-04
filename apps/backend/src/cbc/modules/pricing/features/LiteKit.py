"""/lite-kit under /api/reference - lite-kit list prices.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from cbc.modules.ops.api import audit
from cbc.modules.pricing.api import reference_library as reflib
from cbc.modules.pricing.domain.reference_updates import LiteKitCell, LiteKitReplace
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


def _set_cell(document: dict[str, Any], body: LiteKitCell) -> tuple[dict[str, Any], Any]:
    """Write one price into one table. Returns (document, the price it replaced)."""
    tables = document.get("tables") or []
    if body.table >= len(tables):
        raise HTTPException(404, f"no lite-kit table {body.table} ({len(tables)} on file)")
    prices = tables[body.table].setdefault("prices", {})
    row = prices.setdefault(str(body.height), {})
    before = row.get(str(body.width))
    row[str(body.width)] = body.price
    return document, before


@router.patch("/lite-kit")
async def patch_lite_kit(body: LiteKitCell, actor: AdminActor) -> dict[str, Any]:
    """Set one list price, addressed by table and size.

    The PUT beside this replaces the whole document, which is what the settings
    screen used to send for a single cell: its audit entry could record only a
    table count, so "who changed this price, and from what?" had no answer, and
    two people editing different tables overwrote each other because each posted
    back the copy they had loaded. PUT stays for a bulk re-import.
    """
    document = await run_sync(reflib.load_lite_kit_prices)
    document, before = _set_cell(document, body)
    after = await run_sync(reflib.update_lite_kit_prices, document)
    await audit.record(
        "reference.lite_kit.cell",
        actor,
        audit_family("lite_kit_prices"),
        before={"price": before},
        after={
            "table": body.table,
            "width": body.width,
            "height": body.height,
            "price": body.price,
        },
    )
    return after
