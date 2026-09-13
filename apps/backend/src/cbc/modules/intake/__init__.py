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
        DeleteDocument,
        ListVersions,
        GetVersion,
        CreateVersion,
        DiffVersion,
        MarkReconciled,
    ):
        app.include_router(feature.router)


async def ensure_indexes() -> None:
    from cbc.modules.intake.infrastructure.collections import ensure_indexes as build

    await build()
