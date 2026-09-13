"""GET /api/projects/{code}/documents - a bid's documents, oldest first.
"""
from __future__ import annotations

from fastapi import APIRouter

from cbc.modules.projects.api.lookup import load
from cbc.modules.intake.infrastructure.collections import documents
from cbc.shared.mongo import serialise

router = APIRouter(prefix="/api/projects/{code}/documents", tags=["documents"])


@router.get("")
async def list_documents(code: str) -> dict:
    project = await load(code)
    docs = await documents().find({"projectId": project["_id"]}).sort("uploadedAt", 1).to_list(200)
    return {"documents": serialise(docs)}
