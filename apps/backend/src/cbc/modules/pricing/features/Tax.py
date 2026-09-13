"""/tax under /api/reference - sales tax rates.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from cbc.modules.pricing.api import calc
from cbc.modules.ops.api import audit
from cbc.modules.pricing.api import reference_library as reflib
from cbc.modules.pricing.domain.reference_updates import TaxRatesUpdate
from cbc.modules.pricing.infrastructure.reference_io import audit_family, run_sync
from cbc.shared.auth import Actor, AdminActor

router = APIRouter(prefix="/api/reference", tags=["reference"])


def _tax() -> dict[str, Any]:
    payload = reflib.load_tax_rates()
    return {
        "rates": calc.tax_rates(),
        "description": payload.get("description"),
        "source": payload.get("source"),
        "note": payload.get("note"),
    }


@router.get("/tax")
async def get_tax(actor: Actor) -> dict[str, Any]:
    try:
        return await run_sync(_tax)
    except (FileNotFoundError, KeyError, OSError) as exc:
        raise HTTPException(404, "sales tax data is missing") from exc


@router.patch("/tax")
async def update_tax(body: TaxRatesUpdate, actor: AdminActor) -> dict[str, Any]:
    if not body.rates and not body.remove:
        return await run_sync(_tax)

    before = (await run_sync(reflib.load_tax_rates)).get("rates", {})
    try:
        await run_sync(reflib.update_tax_rates, rates=body.rates, remove=body.remove)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    after = (await run_sync(reflib.load_tax_rates)).get("rates", {})
    touched = set(before) | set(after)
    changed = {
        code: after.get(code) for code in touched if before.get(code) != after.get(code)
    }
    await audit.record(
        "reference.tax.update",
        actor,
        audit_family("tax"),
        before={code: before.get(code) for code in changed},
        after=changed,
    )
    return await run_sync(_tax)
