"""The quotation, review summary and email draft a run leaves behind."""
from __future__ import annotations

import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz

from cbc.modules.ops.api.artifact_gate import ArtifactValidationError
from cbc.modules.quoting.infrastructure.collections import proposals
from cbc.shared import pdfcheck, storage
from cbc.shared.paths import storage_root
from cbc.modules.quoting.infrastructure import render
from cbc.modules.extraction.api.validation import review as review_flags

log = logging.getLogger("cbc.services.sync")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pdf_problems(content: bytes, label: str) -> list[str]:
    """The shared structural check. Extraction gates on the same one."""
    return pdfcheck.pdf_problems(content, label)


def check_proposal_pdf(project: str) -> tuple[list[str], list[str]]:
    """Validate existing PDF exports, including the copy offered for delivery.

    Absence is allowed during the pre-render gate: the worker creates the PDF
    afterwards, or records the unavailable local renderer in the email draft.
    """
    root = storage_root() / project
    problems: list[str] = []
    for relative in ("quotation.pdf", "uploads/final/quotation.pdf"):
        path = root / relative
        if path.exists():
            try:
                problems.extend(_pdf_problems(path.read_bytes(), f"{project}/{relative}"))
            except OSError as exc:
                problems.append(f"{project}/{relative}: PDF could not be read: {exc}")
    return problems, []


def _render_delivery(slug: str) -> None:
    """Export exactly the worker-rendered HTML, then publish local final copies."""
    import json

    root = storage_root() / slug
    html = root / "quotation.html"
    pdf = root / "quotation.pdf"
    final = root / "uploads" / "final"
    final.mkdir(parents=True, exist_ok=True)
    deliverable: dict[str, Any] = {
        "html": False,
        "pdf": False,
        "pdf_validated": False,
        "pdf_pages": 0,
        "renderer": None,
        "updated_at": _now().isoformat(),
    }
    try:
        from weasyprint import HTML
    except (ImportError, OSError) as exc:
        # An older export must not survive and masquerade as this run's PDF.
        pdf.unlink(missing_ok=True)
        (final / pdf.name).unlink(missing_ok=True)
        email = root / "review" / "quotation_email_draft.md"
        notice = f"\n\nPDF export unavailable: {exc}. HTML is the deliverable; print it to PDF locally.\n"
        storage.atomic_write_text(email, email.read_text(encoding="utf-8") + notice)
        deliverable["renderer"] = "unavailable"
        deliverable["pdf_error"] = str(exc)
    else:
        try:
            start = time.perf_counter()
            content = HTML(filename=str(html), base_url=str(root)).write_pdf()
            deliverable["pdf_ms"] = round((time.perf_counter() - start) * 1000, 1)
        except Exception as exc:
            raise ArtifactValidationError(f"{slug}: PDF export failed: {exc}") from exc
        problems = _pdf_problems(content, f"{slug}/quotation.pdf")
        if problems:
            raise ArtifactValidationError("; ".join(problems))
        pdf.write_bytes(content)
        shutil.copy2(pdf, final / pdf.name)
        deliverable["pdf"] = True
        deliverable["pdf_validated"] = True
        deliverable["renderer"] = "weasyprint"
        try:
            with fitz.open(stream=content, filetype="pdf") as document:
                deliverable["pdf_pages"] = document.page_count
        except Exception:
            deliverable["pdf_pages"] = 0
        # The number that decides whether headless Chromium is ever worth ~300MB
        # in the worker image: one PDF per bid, at the end of a ~20-minute run.
        log.info(
            "%s: rendered quotation.pdf in %s ms (%d page(s))",
            slug,
            deliverable.get("pdf_ms"),
            deliverable["pdf_pages"],
        )
    if html.is_file():
        shutil.copy2(html, final / html.name)
        deliverable["html"] = True
    review = root / "review"
    review.mkdir(parents=True, exist_ok=True)
    (review / "deliverables.json").write_text(
        json.dumps(deliverable, indent=2), encoding="utf-8"
    )


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
    results = [render.render_quotation(slug), render.render_review_summary(slug)]
    for result in results:
        if not result.ok:
            pass_log.warning("%s: %s", job_type, result.detail)
            failed.append(result.detail)
    if not failed:
        # The PDF rides the same sha keys as the HTML: if both renders were
        # unchanged and a valid PDF already exists, WeasyPrint has nothing to do.
        # A template edit or RENDERER_VERSION bump moves those keys and re-renders
        # both, so the PDF invalidates automatically - no second stamp needed.
        pdf = storage_root() / slug / "quotation.pdf"
        if any(not r.unchanged for r in results) or not pdf.is_file():
            _render_delivery(slug)
        else:
            pass_log.info("%s: quotation.pdf is current; skipping PDF render", job_type)
    return failed
