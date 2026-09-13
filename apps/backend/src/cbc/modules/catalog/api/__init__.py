"""catalog's public surface - the only part of catalog another module may import.

- `products.get`, `products.by_part` - a part, for the modules that price and quote it.
- `search.index_available` - whether any price book has been indexed, for health.
- `jobs` - index_catalog, delete_catalog and ingest_pricebook, for the worker's runner.
"""
