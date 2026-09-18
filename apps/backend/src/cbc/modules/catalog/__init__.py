"""catalog: the parts CBC can quote, and the vendor price books they come from.

Products, price books, and the jobs that describe each book's pages into the page
index. It owns `catalogItems`, `priceBooks`, `pageIndex` and `matchLearning`,
which `api/pageindex` builds, stores and reads.

`matchLearning` is what an estimator has confirmed a specification means (FR-13).
`api/learning` is how it is written and recalled; extraction drains its own
correction queue into it, because the queue is extraction's and the table is ours.

Other modules import only `cbc.modules.catalog.api`. Slices are imported inside
`register`, so a module that only wants a part does not load every handler.
"""
from __future__ import annotations


def _bind_ports() -> None:
    """Hand pricing the catalog lookup it must not import.

    pricing prices a line off a catalog part, and catalog reads pricing for
    margins and the confidence floor. Importing each other closes a cycle the
    architecture forbids, so catalog hands its lookup over - the same shape
    extraction uses to give projects its opening counts.

    Called from both entry points on purpose: the API runs `register`, the worker
    runs only `register_jobs`, and the backfill that needs this runs *in the
    worker*. Binding in `register` alone would leave it unbound exactly where it
    is used, and the backfill would skip every line without saying why.
    """
    from cbc.modules.catalog.api.pageindex import reader
    from cbc.modules.pricing.api import catalog_baseline_backfill

    catalog_baseline_backfill.bind_catalog_lookup(reader.lookup_catalog_item)


def register(app) -> None:
    """Mount this module's routes on the application."""
    _bind_ports()

    from cbc.modules.catalog.features import (
        CreatePriceBook,
        CreateProduct,
        DeletePriceBook,
        DeleteProduct,
        DownloadPriceBook,
        GetPriceBook,
        GetProduct,
        ListPriceBooks,
        MarkReviewed,
        SearchProducts,
        UpdatePriceBook,
        UpdateProduct,
        UploadPriceBookFile,
    )

    for feature in (
        SearchProducts,
        GetProduct,
        CreateProduct,
        UpdateProduct,
        DeleteProduct,
        ListPriceBooks,
        GetPriceBook,
        CreatePriceBook,
        UploadPriceBookFile,
        DownloadPriceBook,
        UpdatePriceBook,
        MarkReviewed,
        DeletePriceBook,
    ):
        app.include_router(feature.router)


def register_jobs() -> None:
    """Plug this module's jobs into ops' worker."""
    _bind_ports()
    from functools import partial

    from cbc.modules.catalog.features import (
        DeleteCatalog,
        IndexCatalog,
        IngestPricebook,
        ParseCatalog,
        ParseMultiplier,
    )
    from cbc.modules.ops.api import worker

    # Describing a price book's pages is string handling, not reasoning, so these
    # two run in the worker itself. A bad payload, a missing file or a layout the
    # extractor cannot read all read exactly the same on the third attempt, so
    # they fail at once rather than spend the attempt budget reaching it.
    permanent = (ValueError, FileNotFoundError, IndexCatalog.IndexingError)
    parse_permanent = (
        ValueError,
        FileNotFoundError,
        ParseCatalog.ParsePermanent,
        ParseMultiplier.ParsePermanent,
    )
    worker.register("index_catalog", partial(worker.run_locally, work=IndexCatalog.index_catalog, permanent=permanent))
    worker.register("delete_catalog", partial(worker.run_locally, work=DeleteCatalog.delete_catalog, permanent=permanent))
    worker.register(
        "parse_catalog",
        partial(worker.run_locally, work=ParseCatalog.parse_catalog, permanent=parse_permanent),
        after_finish=ParseCatalog.after_finish,
    )
    worker.register(
        "parse_multiplier",
        partial(
            worker.run_locally, work=ParseMultiplier.parse_multiplier, permanent=parse_permanent
        ),
        after_finish=ParseMultiplier.after_finish,
    )
    worker.register("ingest_pricebook", IngestPricebook.run)


async def ensure_indexes() -> None:
    from cbc.modules.catalog.infrastructure.collections import ensure_indexes as build

    await build()
