"""catalog's public surface - the only part of catalog another module may import.

- `products.get`, `products.by_part` - a part, for the modules that price and quote it.
- `matchcache` - a bid's high-confidence product matches, reused while the catalog
  and the door schedule behind them are unchanged.
- `pageindex` - each price book's page index: `reader` and `query` for the catalog MCP
  server (read-only), `build` and `store` for the worker, the API root and the scripts.
- `search.index_available` - whether any price book has been indexed, for health.
"""
