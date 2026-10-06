"""POST /api/projects/{code}/quote/lines/{line_id}/adders/{index} - add a list adder the legend names (NR-4).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from cbc.modules.ops.api import audit
from cbc.modules.pricing.api import calc
from cbc.modules.projects.api.lookup import load
from cbc.modules.quoting.api import quote as quote_service
from cbc.modules.quoting.infrastructure.collections import estimate_lines
from cbc.shared.auth import Actor
from cbc.shared.mongo import oid, serialise

router = APIRouter(prefix="/api/projects/{code}/quote", tags=["quote"])


@router.post("/lines/{line_id}/adders/{index}")
async def add_adder(code: str, line_id: str, index: int, actor: Actor) -> dict:
    """An adder is a list value: it goes on the list price, and the line's own
    multiplier applies to the sum - the price book's rule, through calc."""
    project = await load(code)
    line = await estimate_lines().find_one({"_id": oid(line_id), "projectId": project["_id"]})
    if not line:
        raise HTTPException(404, "quote line not found")
    candidates = line.get("adderCandidates") or []
    if not 0 <= index < len(candidates):
        raise HTTPException(404, "this line has no such adder")
    if line.get("listPrice") is None or not line.get("multiplier"):
        raise HTTPException(409, "this line is not priced from a list price - add the adder to its cost by hand")

    adder = candidates[index]
    applied = [*(line.get("appliedAdders") or []), adder]
    priced = calc.cost_from_list(
        float(line["listPrice"]), float(line["multiplier"]),
        [{"name": a["name"], "list_adder": a["listAdder"]} for a in applied],
    )
    after = {
        "cost": priced["cost"],
        "costSourceDetail": f"{line.get('costSourceDetail') or ''}; + {adder['name']} list adder "
                            f"${float(adder['listAdder']):.2f}".lstrip("; "),
        "appliedAdders": applied,
        "adderCandidates": [a for i, a in enumerate(candidates) if i != index],
    }
    before = {key: line.get(key) for key in after}
    reason = f"added the {adder['name']} list adder"
    now = datetime.now(timezone.utc)
    await estimate_lines().update_one(
        {"_id": line["_id"]},
        {
            "$set": {**after, "updatedAt": now},
            # An estimator's edit: a re-price keeps the cost, and the adder stays added.
            "$push": {"overrides": {"at": now, "by": actor, "before": before, "after": after, "reason": reason}},
            **({"$pull": {"flags": "adder_named"}} if not after["adderCandidates"] else {}),
        },
    )
    await audit.record("quote.adder_added", actor, {"projectId": project["_id"], "quoteLineId": line["_id"]},
                       before=before, after=after, note=reason)
    totals = await quote_service.persist(project)
    return {"line": serialise(await estimate_lines().find_one({"_id": line["_id"]})), "totals": totals}
