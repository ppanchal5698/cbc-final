"""intake: getting a bid set in - document uploads, pages, and addendum versions.

It owns `documents` and `estimateVersions`. Other modules import only
`cbc.modules.intake.api`. Slices are imported inside `register`.
"""
from __future__ import annotations


def register(app) -> None:
    """Mount this module's routes, and plug in what it supplies to projects."""
    from cbc.modules.intake.api import documents as documents_api
    from cbc.modules.intake.infrastructure.collections import delete_for_project
    from cbc.modules.projects.api import bids, board_sources
    from cbc.shared import events

    # projects may not import intake - intake depends on projects - so intake
    # supplies the board's document counts and listens for a bid being deleted.
    board_sources.bind_document_counts(documents_api.count_by_project)
    events.subscribe(bids.PROJECT_DELETED, delete_for_project)

    from cbc.modules.intake.features import (
        CreateVersion,
        DeleteDocument,
        DiffVersion,
        DownloadDocument,
        GetPageSize,
        GetVersion,
        ListDocuments,
        ListPageBlocks,
        ListVersions,
        MarkReconciled,
        RenderPage,
        UploadDocument,
    )

    for feature in (
        ListDocuments,
        UploadDocument,
        DownloadDocument,
        RenderPage,
        GetPageSize,
        ListPageBlocks,
        DeleteDocument,
        ListVersions,
        GetVersion,
        CreateVersion,
        DiffVersion,
        MarkReconciled,
    ):
        app.include_router(feature.router)


def register_jobs() -> None:
    """Plug this module's jobs into ops' worker, and supply the documents an extract reads."""
    from functools import partial

    from cbc.modules.extraction.api import documents as extraction_documents
    from cbc.modules.intake.api import documents as documents_api
    from cbc.modules.intake.features import IngestAddendum, ParseDocument, RunFullPipeline
    from cbc.modules.ops.api import worker

    # extraction may not import intake, which depends on it: intake supplies the
    # documents an extract marks read and counts late uploads in.
    extraction_documents.bind(
        documents_api.mark_received,
        documents_api.count_received_after,
        documents_api.parse_signals_by_path,
    )
    # ops may not import intake: supply incomplete parses so Claude waits.
    worker.bind_parse_status(incomplete_parses=documents_api.incomplete_parses)
    worker.register("ingest_addendum", IngestAddendum.run)
    worker.register("run_full_pipeline", RunFullPipeline.run)
    permanent = (ParseDocument.ParsePermanent, ValueError, FileNotFoundError)
    worker.register(
        "parse_document",
        partial(
            worker.run_locally,
            work=ParseDocument.parse_document,
            permanent=permanent,
        ),
        after_finish=ParseDocument.after_finish,
    )


async def ensure_indexes() -> None:
    from cbc.modules.intake.infrastructure.collections import ensure_indexes as build

    await build()
