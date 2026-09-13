"""catalog: the parts CBC can quote, and the vendor price books they come from.

Products, price books, and the jobs that describe each book's pages into the page
index. It owns `catalogItems`, `priceBooks` and `pageIndex`,
which `api/pageindex` builds, stores and reads.

Other modules import only `cbc.modules.catalog.api`. Slices are imported inside
`register`, so a module that only wants a part does not load every handler.
"""
from __future__ import annotations


def register(app) -> None:
    """Mount this module's routes on the application."""
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
    from functools import partial

    from cbc.modules.catalog.features import DeleteCatalog, IndexCatalog, IngestPricebook
    from cbc.modules.ops.api import worker

    # Describing a price book's pages is string handling, not reasoning, so these
    # two run in the worker itself. A bad payload, a missing file or a layout the
    # extractor cannot read all read exactly the same on the third attempt, so
    # they fail at once rather than spend the attempt budget reaching it.
    permanent = (ValueError, FileNotFoundError, IndexCatalog.IndexingError)
    worker.register("index_catalog", partial(worker.run_locally, work=IndexCatalog.index_catalog, permanent=permanent))
    worker.register("delete_catalog", partial(worker.run_locally, work=DeleteCatalog.delete_catalog, permanent=permanent))
    worker.register("ingest_pricebook", IngestPricebook.run)


async def ensure_indexes() -> None:
    from cbc.modules.catalog.infrastructure.collections import ensure_indexes as build

    await build()
