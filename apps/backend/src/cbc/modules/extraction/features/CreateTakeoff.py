"""POST /api/projects/{code}/takeoffs - record FRP geometry; conversion waits on CBC's constants.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from cbc.modules.extraction.infrastructure.collections import takeoffs
from cbc.modules.projects.api.lookup import load
from cbc.shared.persistence import repos
from cbc.shared.auth import Actor
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/projects/{code}", tags=["operational"])


class TakeoffCreate(BaseModel):
    takeoffType: str = "frp"
    perimeterLf: float | None = None
    insideCorners: int | None = None
    outsideCorners: int | None = None
    wallHeightFt: float | None = None
    notes: str | None = None


@router.post("/takeoffs", status_code=201)
async def create_takeoff(code: str, body: TakeoffCreate, actor: Actor) -> dict:
    project = await load(code)
    coll = await repos.for_project(takeoffs(), project, actor)
    document = {
        "bidRequestId": project["_id"],
        "projectId": project["_id"],
        "takeoffType": body.takeoffType,
        "perimeterLf": body.perimeterLf,
        "insideCorners": body.insideCorners,
        "outsideCorners": body.outsideCorners,
        "wallHeightFt": body.wallHeightFt,
        "notes": body.notes,
        "constantsUsed": None,
        "status": "pendingConstants",
        "flags": ["Open Item 5: FRP conversion constants owed by CBC"],
    }
    result = await coll.insert(document)
    document["_id"] = result.inserted_id
    return serialise(document)
