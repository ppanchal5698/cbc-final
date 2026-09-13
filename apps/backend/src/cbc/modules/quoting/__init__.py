"""quoting: the customer-facing document - priced lines, totals, the proposal, RFQs and RFIs.

It owns `estimateLines`, `quotes`, `proposals`, `vendorRfqs` and `rfis`. The
proposal is where the system stops: it renders and routes, and never sends (NFR-1).

Other modules import only `cbc.modules.quoting.api`. Slices are imported inside
`register`.
"""
from __future__ import annotations


def register(app) -> None:
    """Mount this module's routes, and plug in what it supplies to projects."""
    from cbc.modules.projects.api import bids, board_sources
    from cbc.modules.quoting.api import quote as quote_api
    from cbc.modules.quoting.infrastructure.collections import delete_for_project
    from cbc.shared import events

    # projects may not import quoting, which depends on it: quoting supplies the
    # board's quote totals and listens for a bid being deleted.
    board_sources.bind_quotes(quote_api.by_project)
    events.subscribe(bids.PROJECT_DELETED, delete_for_project)

    from cbc.modules.quoting.features import (
        AddQuoteLine,
        AssignToAlternate,
        ContinueToProposal,
        CreateAlternate,
        CreateRfi,
        CreateVendorRfq,
        DeleteQuoteLine,
        EmailDraft,
        GetProposal,
        GetQuote,
        ListAlternates,
        ListRfis,
        ListVendorRfqs,
        MarkComplete,
        ProposalPdf,
        RenderProposal,
        UpdateProposal,
        UpdateQuoteLine,
        UpdateQuoteSettings,
        UpdateVendorRfqStatus,
    )

    for feature in (
        ListAlternates,
        CreateAlternate,
        AssignToAlternate,
        GetQuote,
        UpdateQuoteSettings,
        AddQuoteLine,
        UpdateQuoteLine,
        DeleteQuoteLine,
        ContinueToProposal,
        GetProposal,
        UpdateProposal,
        RenderProposal,
        ProposalPdf,
        MarkComplete,
        EmailDraft,
        ListVendorRfqs,
        CreateVendorRfq,
        UpdateVendorRfqStatus,
        ListRfis,
        CreateRfi,
    ):
        app.include_router(feature.router)


async def ensure_indexes() -> None:
    from cbc.modules.quoting.infrastructure.collections import ensure_indexes as build

    await build()
