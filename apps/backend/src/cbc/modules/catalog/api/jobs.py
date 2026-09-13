"""The catalog's jobs, as the worker's runner calls them.

index_catalog and delete_catalog run inside the worker - describing a price
book's pages is string handling, not reasoning. ingest_pricebook is the second
half of a Claude pass: loading the parts it read off a sheet into the catalog.
"""
from __future__ import annotations

from cbc.modules.catalog.features.DeleteCatalog import delete_catalog
from cbc.modules.catalog.features.IndexCatalog import IndexingError, index_catalog
from cbc.modules.catalog.features.IngestPricebook import ingest_pricebook

__all__ = ["IndexingError", "delete_catalog", "index_catalog", "ingest_pricebook"]
