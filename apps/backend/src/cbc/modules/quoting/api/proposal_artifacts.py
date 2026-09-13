"""The quotation, review summary and email draft a run leaves behind."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from cbc.modules.quoting.infrastructure.collections import proposals
from cbc.shared import storage
from cbc.modules.quoting.infrastructure import render
from cbc.validation import review as review_flags

log = logging.getLogger("cbc.services.sync")


def _now() -> datetime:
    return datetime.now(timezone.utc)


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

    await proposals().update_one(
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


def render_artifacts(job_type: str, slug: str) -> list[str]:
    """Derive the review flags, then render the quotation and review summary; what failed, as details.

    Blocking - run it in a thread. The scripts render both every time, so the
    markup and the arithmetic never come from whatever a pass decided to write.
    Failures are reported rather than raised: a project whose artifacts are too
    broken to derive flags from is a project whose flags the estimator most needs,
    and losing the job would take the rest of the pass with it.
    """
    pass_log = logging.getLogger("cbc.worker")
    try:
        count = review_flags.write_flags(slug)
        pass_log.info("%s: %d review flag(s) derived", job_type, count)
    except Exception:
        pass_log.exception("%s: could not derive review flags for %s", job_type, slug)
    failed: list[str] = []
    for result in (render.render_quotation(slug), render.render_review_summary(slug)):
        if not result.ok:
            pass_log.warning("%s: %s", job_type, result.detail)
            failed.append(result.detail)
    return failed
