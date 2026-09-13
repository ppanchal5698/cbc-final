"""Editable reference data (pricing configuration).

Live source of truth is Mongo `referenceData` (seeded from REFERENCE_DIR JSON).
Editing here is the deliberate, human-initiated act the file-safety rule allows.
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from cbc.core import calc
from cbc.shared.auth import Actor, AdminActor
from cbc.schemas import (
    CustomOtherMatrixReplace,
    FinishesUpdate,
    FrameDepthsUpdate,
    FrpConstantsUpdate,
    HagerAddersUpdate,
    LiteKitReplace,
    MarginFrameworkUpdate,
    SpecialMarginsUpdate,
    SpecialNetsUpdate,
    StockUpdate,
    TaxRatesUpdate,
    VendorCategoriesUpdate,
)
from cbc.modules.ops.api import audit
from cbc.services import reference_library as reflib
from cbc.services import reference_store

router = APIRouter(prefix="/api/reference", tags=["reference"])


async def _run_sync(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


def _audit_family(family: str) -> dict[str, str]:
    return {"family": family, "collection": "referenceData"}


def _framework() -> dict[str, Any]:
    payload = reflib.load_margins()
    return {
        "bands": payload.get("bands", []),
        "accessoriesDerived": payload.get("accessories_derived"),
        "formula": payload.get("formula"),
        "overridable": payload.get("overridable"),
        "governance": payload.get("governance"),
        "source": payload.get("source"),
        "effective": calc.bands(),
    }


def _tax() -> dict[str, Any]:
    payload = reflib.load_tax_rates()
    return {
        "rates": calc.tax_rates(),
        "description": payload.get("description"),
        "source": payload.get("source"),
        "note": payload.get("note"),
    }


@router.get("/margins")
async def get_margins(actor: Actor) -> dict[str, Any]:
    try:
        return await _run_sync(_framework)
    except (FileNotFoundError, KeyError, OSError) as exc:
        raise HTTPException(404, "margin framework is missing") from exc


@router.patch("/margins")
async def update_margins(body: MarginFrameworkUpdate, actor: AdminActor) -> dict[str, Any]:
    if not body.bands and body.accessories is None:
        return await _run_sync(_framework)

    before = await _run_sync(reflib.load_margins)
    before_bands = {b.get("key"): b.get("margin") for b in before.get("bands", [])}
    before_bands["accessories"] = before.get("accessories_derived")

    try:
        await _run_sync(reflib.update_margins, bands=body.bands, accessories=body.accessories)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    after = await _run_sync(reflib.load_margins)
    after_bands = {b.get("key"): b.get("margin") for b in after.get("bands", [])}
    after_bands["accessories"] = after.get("accessories_derived")

    changed = {
        key: value for key, value in after_bands.items() if before_bands.get(key) != value
    }
    await audit.record(
        "reference.margins.update",
        actor,
        _audit_family("margins"),
        before={key: before_bands.get(key) for key in changed},
        after=changed,
    )
    return await _run_sync(_framework)


@router.get("/tax")
async def get_tax(actor: Actor) -> dict[str, Any]:
    try:
        return await _run_sync(_tax)
    except (FileNotFoundError, KeyError, OSError) as exc:
        raise HTTPException(404, "sales tax data is missing") from exc


@router.patch("/tax")
async def update_tax(body: TaxRatesUpdate, actor: AdminActor) -> dict[str, Any]:
    if not body.rates and not body.remove:
        return await _run_sync(_tax)

    before = (await _run_sync(reflib.load_tax_rates)).get("rates", {})
    try:
        await _run_sync(reflib.update_tax_rates, rates=body.rates, remove=body.remove)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    after = (await _run_sync(reflib.load_tax_rates)).get("rates", {})
    touched = set(before) | set(after)
    changed = {
        code: after.get(code) for code in touched if before.get(code) != after.get(code)
    }
    await audit.record(
        "reference.tax.update",
        actor,
        _audit_family("tax"),
        before={code: before.get(code) for code in changed},
        after=changed,
    )
    return await _run_sync(_tax)


def _adder_items(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        r.get("name"): r.get("list_adder")
        for r in payload.get("hager_list_adders", {}).get("items", [])
    }


def _adders() -> dict[str, Any]:
    payload = reflib.load_adders()
    block = payload.get("hager_list_adders", {})
    return {
        "adderTypes": payload.get("adder_types", []),
        "hagerListAdders": {
            "source": block.get("source"),
            "status": block.get("status"),
            "application": block.get("application"),
            "items": block.get("items", []),
        },
        "pending": payload.get("pending", []),
        "rule": payload.get("rule"),
    }


@router.get("/adders")
async def get_adders(actor: Actor) -> dict[str, Any]:
    try:
        return await _run_sync(_adders)
    except (FileNotFoundError, KeyError, OSError) as exc:
        raise HTTPException(404, "manual adders data is missing") from exc


@router.patch("/adders")
async def update_adders(body: HagerAddersUpdate, actor: AdminActor) -> dict[str, Any]:
    if not body.items and not body.remove:
        return await _run_sync(_adders)

    before = _adder_items(await _run_sync(reflib.load_adders))
    try:
        await _run_sync(reflib.update_hager_adders, items=body.items, remove=body.remove)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    after = _adder_items(await _run_sync(reflib.load_adders))
    touched = set(before) | set(after)
    changed = {name: after.get(name) for name in touched if before.get(name) != after.get(name)}
    await audit.record(
        "reference.adders.update",
        actor,
        _audit_family("manual_adders"),
        before={name: before.get(name) for name in changed},
        after=changed,
    )
    return await _run_sync(_adders)


def _special_margins(payload: dict[str, Any]) -> dict[str, Any]:
    return {c.get("name"): c.get("margin") for c in payload.get("customers", [])}


def _special() -> dict[str, Any]:
    payload = reflib.load_special_margins()
    return {
        "customers": payload.get("customers", []),
        "rule": payload.get("rule"),
        "status": payload.get("status"),
        "description": payload.get("description"),
    }


@router.get("/special-margins")
async def get_special_margins(actor: Actor) -> dict[str, Any]:
    try:
        return await _run_sync(_special)
    except (FileNotFoundError, KeyError, OSError) as exc:
        raise HTTPException(404, "special customer margins data is missing") from exc


@router.patch("/special-margins")
async def update_special_margins(body: SpecialMarginsUpdate, actor: AdminActor) -> dict[str, Any]:
    if not body.customers and not body.remove:
        return await _run_sync(_special)

    before = _special_margins(await _run_sync(reflib.load_special_margins))
    try:
        await _run_sync(
            reflib.update_special_margins,
            customers=[c.model_dump(exclude_unset=True) for c in (body.customers or [])],
            remove=body.remove,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    after = _special_margins(await _run_sync(reflib.load_special_margins))
    touched = set(before) | set(after)
    changed = {name: after.get(name) for name in touched if before.get(name) != after.get(name)}
    await audit.record(
        "reference.special_margins.update",
        actor,
        _audit_family("special_customer_margins"),
        before={name: before.get(name) for name in changed},
        after=changed,
    )
    return await _run_sync(_special)


@router.get("/finishes")
async def get_finishes(actor: Actor) -> dict[str, Any]:
    try:
        return await _run_sync(reflib.load_finishes)
    except (FileNotFoundError, KeyError, OSError) as exc:
        raise HTTPException(404, "finish crosswalk data is missing") from exc


@router.patch("/finishes")
async def update_finishes(body: FinishesUpdate, actor: AdminActor) -> dict[str, Any]:
    if not body.finishes and not body.remove:
        return await _run_sync(reflib.load_finishes)

    before = {f.get("us_code") for f in (await _run_sync(reflib.load_finishes)).get("finishes", [])}
    try:
        await _run_sync(
            reflib.update_finishes,
            finishes=[f.model_dump(exclude_unset=True) for f in (body.finishes or [])],
            remove=body.remove,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    after = {f.get("us_code") for f in (await _run_sync(reflib.load_finishes)).get("finishes", [])}
    await audit.record(
        "reference.finishes.update",
        actor,
        _audit_family("finishes"),
        before=sorted(before),
        after=sorted(after),
    )
    return await _run_sync(reflib.load_finishes)


@router.get("/frame-depths")
async def get_frame_depths(actor: Actor) -> dict[str, Any]:
    try:
        return await _run_sync(reflib.load_frame_depths)
    except (FileNotFoundError, KeyError, OSError) as exc:
        raise HTTPException(404, "frame depths data is missing") from exc


@router.patch("/frame-depths")
async def update_frame_depths(body: FrameDepthsUpdate, actor: AdminActor) -> dict[str, Any]:
    if not body.wall_types and not body.remove:
        return await _run_sync(reflib.load_frame_depths)

    before = {w.get("type") for w in (await _run_sync(reflib.load_frame_depths)).get("wall_types", [])}
    try:
        await _run_sync(
            reflib.update_frame_depths,
            wall_types=[w.model_dump(exclude_unset=True) for w in (body.wall_types or [])],
            remove=body.remove,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    after = {w.get("type") for w in (await _run_sync(reflib.load_frame_depths)).get("wall_types", [])}
    await audit.record(
        "reference.frame_depths.update",
        actor,
        _audit_family("frame_depths"),
        before=sorted(before),
        after=sorted(after),
    )
    return await _run_sync(reflib.load_frame_depths)


@router.get("/frp-constants")
async def get_frp_constants(actor: Actor) -> dict[str, Any]:
    try:
        return await _run_sync(reflib.load_frp_constants)
    except (FileNotFoundError, KeyError, OSError) as exc:
        raise HTTPException(404, "FRP constants data is missing") from exc


@router.patch("/frp-constants")
async def update_frp_constants(body: FrpConstantsUpdate, actor: AdminActor) -> dict[str, Any]:
    values = body.model_dump(exclude_unset=True)
    if not values:
        return await _run_sync(reflib.load_frp_constants)

    before = await _run_sync(reflib.load_frp_constants)
    try:
        after = await _run_sync(reflib.update_frp_constants, values)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    await audit.record(
        "reference.frp_constants.update",
        actor,
        _audit_family("frp_constants"),
        before={field: before.get(field) for field in values} | {"status": before.get("status")},
        after={field: after.get(field) for field in values} | {"status": after.get("status")},
    )
    return after


@router.get("/vendor-tiers")
async def get_vendor_tiers(actor: Actor) -> dict[str, Any]:
    try:
        return await _run_sync(reflib.load_vendor_tiers)
    except (FileNotFoundError, KeyError, OSError) as exc:
        raise HTTPException(404, "vendor tiers data is missing") from exc


@router.patch("/vendor-tiers")
async def patch_vendor_tiers(body: VendorCategoriesUpdate, actor: AdminActor) -> dict[str, Any]:
    try:
        after = await _run_sync(reflib.update_vendor_categories, body.vendor, body.categories)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    await audit.record(
        "reference.vendor_tiers.update",
        actor,
        _audit_family("vendor_tiers"),
        after={"vendor": body.vendor, "categories": body.categories},
    )
    return after


@router.get("/special-nets")
async def get_special_nets(actor: Actor) -> dict[str, Any]:
    try:
        return await _run_sync(reflib.load_special_nets)
    except (FileNotFoundError, KeyError, OSError) as exc:
        raise HTTPException(404, "special nets data is missing") from exc


@router.patch("/special-nets")
async def patch_special_nets(body: SpecialNetsUpdate, actor: AdminActor) -> dict[str, Any]:
    if not body.items and not body.remove:
        return await _run_sync(reflib.load_special_nets)
    try:
        after = await _run_sync(
            reflib.update_special_net_items,
            items=[i.model_dump(exclude_unset=True) for i in (body.items or [])],
            remove=body.remove,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    await audit.record(
        "reference.special_nets.update",
        actor,
        _audit_family("hager_special_nets"),
        after={"items": len(body.items or []), "remove": body.remove or []},
    )
    return after


@router.get("/lite-kit")
async def get_lite_kit(actor: Actor) -> dict[str, Any]:
    try:
        payload = await _run_sync(reflib.load_lite_kit_prices)
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
    after = await _run_sync(reflib.update_lite_kit_prices, body.data)
    await audit.record(
        "reference.lite_kit.update",
        actor,
        _audit_family("lite_kit_prices"),
        after={"tableCount": len(after.get("tables") or [])},
    )
    return after


@router.patch("/lite-kit")
async def patch_lite_kit(body: LiteKitReplace, actor: AdminActor) -> dict[str, Any]:
    """Replace the document (same as PUT) — structured cell UI can deepen later."""
    after = await _run_sync(reflib.update_lite_kit_prices, body.data)
    await audit.record(
        "reference.lite_kit.update",
        actor,
        _audit_family("lite_kit_prices"),
        after={"tableCount": len(after.get("tables") or [])},
    )
    return after


@router.get("/stock/{vendor}")
async def get_stock(vendor: str, actor: Actor) -> dict[str, Any]:
    payload = await _run_sync(reflib.load_stock_list, vendor)
    if payload is None:
        raise HTTPException(404, f"no stock list for vendor {vendor!r}")
    return payload


@router.patch("/stock/{vendor}")
async def patch_stock(vendor: str, body: StockUpdate, actor: AdminActor) -> dict[str, Any]:
    if not body.items and not body.remove:
        payload = await _run_sync(reflib.load_stock_list, vendor)
        if payload is None:
            raise HTTPException(404, f"no stock list for vendor {vendor!r}")
        return payload
    try:
        after = await _run_sync(
            reflib.update_stock_items,
            vendor,
            items=[i.model_dump(exclude_unset=True) for i in (body.items or [])],
            remove=body.remove,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    await audit.record(
        "reference.stock.update",
        actor,
        _audit_family(reflib.stock_family_for(vendor) or "stock"),
        after={"vendor": vendor, "items": len(body.items or []), "remove": body.remove or []},
    )
    return after


@router.get("/custom-other-matrix")
async def get_custom_other_matrix(actor: Actor) -> dict[str, Any]:
    try:
        return await _run_sync(reflib.load_custom_other_matrix)
    except (FileNotFoundError, KeyError, OSError) as exc:
        raise HTTPException(404, "custom/other matrix data is missing") from exc


@router.put("/custom-other-matrix")
async def put_custom_other_matrix(
    body: CustomOtherMatrixReplace, actor: AdminActor
) -> dict[str, Any]:
    after = await _run_sync(reflib.update_custom_other_matrix, body.data)
    await audit.record(
        "reference.custom_other_matrix.update",
        actor,
        _audit_family("custom_other_matrix"),
    )
    return after


@router.delete("/{family}/entries/{key}")
async def delete_entry(family: str, key: str, actor: AdminActor) -> dict[str, Any]:
    if family not in reference_store.FAMILIES:
        raise HTTPException(404, f"unknown family {family!r}")
    try:
        after = await _run_sync(reflib.delete_family_entry, family, key)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    await audit.record(
        "reference.entry.delete",
        actor,
        _audit_family(family),
        after={"key": key},
    )
    return after
