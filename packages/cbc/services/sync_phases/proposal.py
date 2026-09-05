"""The quotation, review summary and email draft a run leaves behind."""
from __future__ import annotations

import logging
from typing import Any

from cbc.db import db
from cbc.services import storage
from cbc.services.sync_phases._common import _now

log = logging.getLogger("cbc.services.sync")


async def import_proposal_artifacts(project: dict[str, Any]) -> dict[str, bool]:
    """Record Claude's proposal artifacts without replacing API-rendered totals."""
    slug = project["slug"]
    root = storage.project_dir(slug)
    artifacts = {
        "quotationHtml": (root / "quotation.html").exists(),
        "reviewFlags": (root / "review" / "review_flags.json").exists(),
        "reviewSummary": (root / "review" / "review_summary.html").exists(),
        "emailDraft": (root / "review" / "quotation_email_draft.md").exists(),
    }
    paths: dict[str, str] = {}
    for field, rel in {
        "quotationHtmlPath": "quotation.html",
        "reviewFlagsPath": "review/review_flags.json",
        "reviewSummaryPath": "review/review_summary.html",
        "emailDraftPath": "review/quotation_email_draft.md",
    }.items():
        target = root / rel
        if target.exists():
            paths[field] = storage.relative(target)

    await db.proposals.update_one(
        {"projectId": project["_id"]},
        {
            "$set": {
                **paths,
                "claudeArtifacts": artifacts,
                "artifactsImportedAt": _now(),
                "updatedAt": _now(),
            },
            "$setOnInsert": {
                "projectId": project["_id"],
                "createdAt": _now(),
            },
        },
        upsert=True,
    )
    return artifacts
