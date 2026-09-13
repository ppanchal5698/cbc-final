"""catalog: the parts CBC can quote, and the vendor price books they come from.

Products, price books, and the jobs that describe each book's pages into the page
index. It owns `catalogItems` and `priceBooks`; `pageIndex` is written by
cbc.pageindex, which the catalog's jobs drive.

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


async def ensure_indexes() -> None:
    from cbc.modules.catalog.infrastructure.collections import ensure_indexes as build

    await build()
