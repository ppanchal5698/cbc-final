"""GET /api/projects/{code}/vendor-rfqs - the vendor quote requests on a bid (FR-16).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.infrastructure.collections import vendor_rfqs
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/projects/{code}", tags=["operational"])


@router.get("/vendor-rfqs")
async def list_vendor_rfqs(code: str) -> dict[str, Any]:
    project = await load(code)
    rows = await vendor_rfqs().find({"bidRequestId": project["_id"]}).to_list(500)
    return {"vendorRfqs": serialise(rows)}
