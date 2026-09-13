"""extraction: what the drawings say - the openings an estimator confirms or corrects.

Openings and their alternates, FRP takeoffs, the corrections an estimator makes,
and the Claude payloads that failed the schema gate. It owns `openings`,
`failedExtractions`, `takeoffs` and `feedbackEvents`.

Other modules import only `cbc.modules.extraction.api`. Slices are imported inside
`register`.
"""
from __future__ import annotations


def register(app) -> None:
    """Mount this module's routes, and plug in what it supplies to projects."""
    from cbc.modules.extraction.api import openings as openings_api
    from cbc.modules.extraction.infrastructure.collections import delete_for_project
    from cbc.modules.projects.api import bids, board_sources
    from cbc.shared import events

    # projects may not import extraction, which depends on it: extraction supplies
    # the board's opening counts and listens for a bid being deleted.
    board_sources.bind_opening_counts(openings_api.counts_by_project)
    events.subscribe(bids.PROJECT_DELETED, delete_for_project)

    from cbc.modules.extraction.features import (
        AddLineItemByHand,
        AssignToAlternate,
        BulkLineItemAction,
        ConfirmAllLineItems,
        ConfirmLineItem,
        ContinueToQuote,
        CreateAlternate,
        CreateTakeoff,
        DeleteLineItem,
        ListAlternates,
        ListFeedback,
        ListLineItems,
        ListTakeoffs,
        RerunExtraction,
        ResolveDuplicate,
        UpdateLineItem,
    )

    for feature in (
        ListLineItems,
        AddLineItemByHand,
        UpdateLineItem,
        ConfirmLineItem,
        ConfirmAllLineItems,
        BulkLineItemAction,
        ResolveDuplicate,
        DeleteLineItem,
        RerunExtraction,
        ContinueToQuote,
        ListAlternates,
        CreateAlternate,
        AssignToAlternate,
        ListTakeoffs,
        CreateTakeoff,
        ListFeedback,
    ):
        app.include_router(feature.router)


async def ensure_indexes() -> None:
    from cbc.modules.extraction.infrastructure.collections import ensure_indexes as build

    await build()
