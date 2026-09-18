"""POST /api/projects/{code}/documents - upload a PDF and wake the pipeline.

Uploading a building plan is the event the whole pipeline hangs off: the file
lands in `projects/{slug}/uploads/raw/`, a document row is written, and an
`extract_bid_set` job is enqueued for the worker to pick up.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile

from cbc.modules.intake.infrastructure.collections import documents
from cbc.modules.intake.infrastructure.snapshot import snapshot
from cbc.modules.ops.api import audit, jobs as job_service, parsing_config
from cbc.modules.ops.api.jobs import enqueue, enqueue_pipeline, reserve
from cbc.modules.projects.api.lookup import load
from cbc.modules.intake.infrastructure import pdf
from cbc.shared import storage
from cbc.shared.auth import Actor
from cbc.shared.config import settings
from cbc.shared.mongo import run_transaction, serialise

router = APIRouter(prefix="/api/projects/{code}/documents", tags=["documents"])


PDF_MAGIC = b"%PDF-"


@router.post("")
async def upload_document(
    code: str,
    actor: Actor,
    response: Response,
    file: UploadFile = File(...),
    kind: str = Form("plan"),
) -> dict:
    project = await load(code)

    # Which job this upload becomes, decided before anything is written so the
    # conflict check can refuse without leaving a file, a document row and a
    # version behind it.
    # Autopilot no longer uses a single run_full_pipeline job. It starts the
    # domain chain at extract_bid_set with payload.orchestrate=true; workers
    # enqueue the next phase when each step succeeds.
    job_type = "ingest_addendum" if kind == "addendum" else "extract_bid_set"
    superseded = await reserve(project["_id"], job_type)

    storage.scaffold(project["slug"])
    target = storage.unique_filename(storage.raw_dir(project["slug"]), file.filename or "upload.pdf")
    try:
        size = await storage.receive_upload(
            file, target, settings.max_upload_bytes, magic=PDF_MAGIC
        )
    except ValueError as exc:
        detail = str(exc)
        if "exceeds" in detail:
            status = 413
        elif "malware" in detail.lower() or "scanner" in detail.lower():
            status = 422
        else:
            status = 415
        raise HTTPException(status, detail) from exc

    # A bid set is a CAD export; counting its pages is real work, and doing it
    # inline blocked every other request - including the health check - for the
    # duration.
    try:
        pages = await asyncio.to_thread(pdf.page_count, target)
    except Exception:
        target.unlink(missing_ok=True)
        raise HTTPException(422, "could not read that PDF - it may be corrupt")

    content_sha = await asyncio.to_thread(storage.content_sha256, target)
    existing = await documents().find_one(
        {"projectId": project["_id"], "contentSha": content_sha}
    )
    if existing:
        # Same bytes already on this bid — drop the duplicate file and do not
        # start a second extract. If an extract is already queued, nudge coalesce.
        target.unlink(missing_ok=True)
        active = await job_service.active_pipeline_job(project["_id"])
        job = active
        if (
            active
            and active["type"] == job_type
            and active["status"] == "queued"
            and job_type == "extract_bid_set"
        ):
            job = (
                await job_service.extend_queued_coalesce(
                    active["_id"], job_service.DEFAULT_COALESCE_SECONDS
                )
                or active
            )
        response.status_code = 200
        return {
            "document": serialise(existing),
            "job": serialise(job) if job else None,
            "autopilot": bool(project.get("autopilot")) and kind != "addendum",
            "version": None,
            "waitingForSiblings": bool(job and job_service.waiting_for_siblings(job)),
            "stragglerPending": bool(job.get("stragglerPending")) if job else False,
            "note": "Identical PDF already on this bid; skipped duplicate upload.",
            "duplicate": True,
        }

    document = {
        "projectId": project["_id"],
        "filename": target.name,
        "kind": kind,
        "pages": pages,
        "bytes": size,
        "path": storage.relative(target),
        "contentSha": content_sha,
        "state": "received",
        "uploadedAt": datetime.now(timezone.utc),
        "uploadedBy": actor,
    }

    parse_resolved = await parsing_config.load_stored()
    parse_on = parsing_config.enabled(parse_resolved)
    if parse_on:
        document["parse"] = {"state": "queued", "pages": pages}

    # Addendum snapshot is human-facing history; keep it outside the txn so a
    # failed enqueue does not leave a half-applied version number race.
    version = None
    if job_type == "ingest_addendum":
        version = await snapshot(project, f"Addendum: {target.name}", actor)

    async def _persist(session):
        session_kw = {"session": session} if session is not None else {}
        result = await documents().insert_one(document, **session_kw)
        document["_id"] = result.inserted_id
        if parse_on:
            await enqueue(
                "parse_document",
                project["_id"],
                payload={"documentId": str(result.inserted_id), "filename": target.name},
                actor=actor,
                session=session,
            )
        if job_type == "ingest_addendum":
            return await enqueue_pipeline(
                "ingest_addendum",
                project["_id"],
                payload={
                    "documentId": str(result.inserted_id),
                    "filename": target.name,
                    "version": version["version"],
                },
                actor=actor,
                session=session,
            )
        payload = {
            "documentId": str(result.inserted_id),
            "filename": target.name,
        }
        if project.get("autopilot"):
            payload["orchestrate"] = True
        return await enqueue_pipeline(
            "extract_bid_set",
            project["_id"],
            payload=payload,
            actor=actor,
            # several PDFs dropped together are read as one bid set (Matrix 8.0)
            delay_seconds=job_service.DEFAULT_COALESCE_SECONDS,
            session=session,
        )

    try:
        job = await run_transaction(_persist)
    except Exception:
        target.unlink(missing_ok=True)
        raise

    await audit.record(
        "document.upload",
        actor,
        {"projectId": project["_id"], "documentId": document["_id"]},
        after={"kind": kind},
    )

    coalesce = job_service.coalesce_note(job)
    notes = [
        note
        for note in (
            "Prior work was snapshotted; differences will be flagged, not merged."
            if version
            else None,
            # Never cancel an estimator's run without saying so.
            f"A queued {superseded['type']} run was superseded and must be "
            "re-started once the differences have been reviewed."
            if superseded
            else None,
            coalesce,
        )
        if note
    ]

    response.status_code = 201
    return {
        "document": serialise(document),
        "job": serialise(job),
        "autopilot": bool(project.get("autopilot")) and kind != "addendum",
        "version": version["version"] if version else None,
        "waitingForSiblings": job_service.waiting_for_siblings(job),
        "stragglerPending": bool(job.get("stragglerPending")),
        "note": "; ".join(notes) or None,
    }
