# Catalog MinerU JSON + Bbox Evidence for Match/Price

## Summary

Mirror the bid stack (MinerU → `documentPages` → **bid-docs** → optional `pdf-tools` bbox crop) for **pricebooks** and **multiplier PDFs**. `match_and_price` prefers `catalog-docs.search_blocks` (blocks + bbox); `find_pages` / `pageIndex` remain the fallback when parse is off or incomplete.

## Parallel to bids

| Bid | Catalog / multipliers |
|-----|------------------------|
| `parse_document` | `parse_catalog` / `parse_multiplier` |
| `documentPages` | `catalogPages` / `multiplierPages` |
| `uploads/processed/mineru/{docId}/` | `data/pricebooks/processed/mineru/{priceBookId}/` (multipliers: `data/pricebooks/processed/mineru/multipliers/{sheetId}/`) |
| **bid-docs** MCP | **catalog-docs** MCP |
| extract toolset | `match_and_price` toolset includes catalog-docs |

## Agent loop

1. `catalog-docs.search_blocks(query, catalog_id?)` → blocks with bbox, page, `file_path`.
2. Read list / multiplier text from block (incl. table HTML) when clear.
3. If unclear → `pdf-tools.get_page_image(file_path, page, region=bbox)`.
4. `get_multiplier` / calc-engine; emit `priced/line_items.json` with `source_page` + citation in `cost_source_detail`.
5. Sync unchanged: `import_quote_lines` → `quote.persist`.

## Jobs

- **Upload** enqueues `index_catalog` and, when `PARSER_URL` is set, `parse_catalog`.
- **`parse_catalog`**: windowed MinerU; upsert `catalogPages`; hash-skip; soft status on `priceBooks.parse`.
- **`parse_multiplier`**: same for multiplier PDFs (`family`, `sheetId`, path under reference-library).
- Job types are **not** `parse_document` — bid `defer_if_parsing` is unchanged.
- Claimed by **catalog** (and optionally parsing) workers — not mixed into bid extract exclusivity.

## MCP: catalog-docs (read-only)

- `list_catalogs_parsed` — parse state + page counts  
- `get_outline` — per-page titles / block counts  
- `search_blocks` — query → hits with bbox + `file_path` + `pdf_page`  
- `get_page_blocks` — one page, cursor / max_chars  

Requires `MONGODB_READONLY_URI` (no writable fallback).

## Gates / delete

- Default: if catalog parse incomplete → agents use `find_pages` (no hard block).
- Optional: `CATALOG_PARSE_WAIT=1` → `defer_if_catalog_parsing` on `match_and_price` while `parse_catalog` queued/running for books that have a file.
- `delete_catalog` purges `pageIndex`, `catalogPages`, and MinerU artefact dirs.

## Failure matrix

| Failure | Behavior |
|---------|----------|
| `PARSER_URL` empty | No parse job; find_pages only |
| Parse queued/running | find_pages fallback (unless wait flag) |
| Parse failed mid-book | Keep last good pages; fallback find_pages |
| Delete book | Purge index + pages + artefacts |

## Non-goals (v1)

- Replacing `pageIndex` or `referenceData` JSON multipliers  
- Qdrant (Phase 2 optional hybrid on same MCP tools)  
- Merging catalog parse into bid `parse_document`  
