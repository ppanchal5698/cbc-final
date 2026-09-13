"""A document, always scoped to the bid in the URL.
"""
from __future__ import annotations

from fastapi import HTTPException

from cbc.modules.projects.api.lookup import load
from cbc.modules.intake.infrastructure.collections import documents
from cbc.shared.mongo import oid


async def find_on_bid(code: str, document_id: str) -> dict:
    """The document, scoped to the bid in the URL.

    Every one of these routes used to look up `{"_id": oid(document_id)}` alone.
    `await load(code)` proved the project existed and its _id was then never
    used, so any signed-in estimator could read or DELETE a document belonging
    to a different bid by id - another customer's drawings, on a system whose
    whole point is that a bid set is confidential. Every sibling router already
    filters on projectId (line_items.py, quote.py, calls.py); one helper here
    means a fifth route cannot quietly regress.
    """
    project = await load(code)
    document = await documents().find_one(
        {"_id": oid(document_id), "projectId": project["_id"]}
    )
    if not document:
        raise HTTPException(404, "document not found")
    return document
