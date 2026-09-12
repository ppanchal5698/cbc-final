"""Integration status visible to every signed-in user."""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


@router.get("")
async def integration_status() -> dict[str, Any]:
    p21_connected = bool(os.environ.get("P21_BASE_URL", "").strip())
    return {
        "p21": {
            "connected": p21_connected,
            "path": 1,
            "requirement": "NR-10",
            "status": "connected" if p21_connected else "deferred",
            "title": "P21 purchase-order cost",
            "summary": "Last PO cost from Prophet 21 for regularly purchased items.",
            "note": (
                "P21 is connected and read-only."
                if p21_connected
                else (
                    "Not connected in this environment. Pricing uses vendor list × "
                    "multiplier or manual entry until integration is enabled."
                )
            ),
            "adminNote": (
                None
                if p21_connected
                else "NR-10 / Path 1 deferred. Set P21_BASE_URL to connect."
            ),
            "fallbacks": [
                "Vendor list price × tier multiplier",
                "Distributor lookup or vendor RFQ",
            ],
        },
    }
