"""Bid documents - upload, list, serve, and the trigger that wakes Claude.

Uploading a building plan is the event the whole pipeline hangs off: the file
lands in `projects/{slug}/uploads/raw/`, a document row is written, and an
`extract_bid_set` job is enqueued for the worker to pick up.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, Response as PlainResponse

from cbc.shared.config import settings
from cbc.db import db
from cbc.shared.mongo import oid, run_transaction, serialise
from cbc.shared.auth import Actor
from cbc.modules.ops.api.jobs import enqueue_pipeline, reserve
from cbc.http.projects_access import load
from cbc.modules.intake.api.routes.versions import snapshot
from cbc.modules.ops.api import audit
from cbc.modules.ops.api import jobs as job_service
from cbc.services import pdf, storage

router = APIRouter(prefix="/api/projects/{code}/documents", tags=["documents"])

PDF_MAGIC = b"%PDF-"

# How long extract_bid_set waits after an upload, so several PDFs dropped
# together are read as one bid set rather than starting a run that misses them
# (Matrix 8.0 — one combined PDF or several separate PDFs). Quiet window default
# 60s; hard cap PIPELINE_COALESCE_MAX_SECONDS (default 300s) lives in jobs.py.
PIPELINE_DEBOUNCE_SECONDS = int(os.environ.get("PIPELINE_DEBOUNCE_SECONDS", "60"))


@router.get("")
async def list_documents(code: str) -> dict:
    project = await load(code)
    docs = await db.documents.find({"projectId": project["_id"]}).sort("uploadedAt", 1).to_list(200)
    return {"documents": serialise(docs)}


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
    existing = await db.documents.find_one(
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
                    active["_id"], PIPELINE_DEBOUNCE_SECONDS
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

    # Addendum snapshot is human-facing history; keep it outside the txn so a
    # failed enqueue does not leave a half-applied version number race.
    version = None
    if job_type == "ingest_addendum":
        version = await snapshot(project, f"Addendum: {target.name}", actor)

    async def _persist(session):
        session_kw = {"session": session} if session is not None else {}
        result = await db.documents.insert_one(document, **session_kw)
        document["_id"] = result.inserted_id
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
            delay_seconds=PIPELINE_DEBOUNCE_SECONDS,
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


async def _document(code: str, document_id: str) -> dict:
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
    document = await db.documents.find_one(
        {"_id": oid(document_id), "projectId": project["_id"]}
    )
    if not document:
        raise HTTPException(404, "document not found")
    return document


@router.get("/{document_id}/file")
async def get_file(code: str, document_id: str) -> FileResponse:
    """Serve the raw PDF so the reviewer sees the actual drawing, not a re-rendering."""
    document = await _document(code, document_id)

    path = storage.absolute(document["path"])
    if not path.exists():
        raise HTTPException(410, f"file missing on disk: {document['path']}")

    return FileResponse(
        path,
        media_type="application/pdf",
        filename=document["filename"],
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/{document_id}/page/{page_number}")
async def get_page(code: str, document_id: str, page_number: int, dpi: int = 110) -> Response:
    """A rendered page image, for viewers that cannot run pdf.js."""
    document = await _document(code, document_id)

    try:
        image = await asyncio.to_thread(
            pdf.render_page, storage.absolute(document["path"]), page_number, dpi
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    return PlainResponse(
        await asyncio.to_thread(image.read_bytes),
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("/{document_id}/page/{page_number}/size")
async def get_page_size(code: str, document_id: str, page_number: int) -> dict:
    """Page dimensions in PDF points - the frame every stored bbox is measured against."""
    document = await _document(code, document_id)
    return await asyncio.to_thread(
        pdf.page_size, storage.absolute(document["path"]), page_number
    )


@router.delete("/{document_id}", status_code=204, response_class=Response)
async def delete_document(code: str, document_id: str, actor: Actor) -> Response:
    """Detach a document from the bid. The file itself stays - raw uploads are immutable."""
    document = await _document(code, document_id)

    await db.documents.delete_one({"_id": document["_id"]})
    await audit.record(
        "document.delete",
        actor,
        {"projectId": document["projectId"], "documentId": document["_id"]},
        before=document.get("filename"),
        note="file retained on disk",
    )
    return Response(status_code=204)
