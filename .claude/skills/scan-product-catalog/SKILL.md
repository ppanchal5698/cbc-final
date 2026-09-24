---
name: scan-product-catalog
description: >
  Finds which page of which vendor price book carries a part - Hager,
  National Guard, PEMKO/Markar, Rockwood, ASI, Bobrick, Bradley, Gamco, World
  Dryer, NUDO - searching by part number, series or description. Returns the
  page to open and why it matched, not a price: the price is read off the sheet.
  Use when a matched item needs a list price before the multiplier is applied.
---

# Scan Product Catalog

## Search strategy

Work down this ladder and stop at the first step that answers:

The catalog tools tell you **which page to open**. They do not return prices,
and nothing stored knows one - the price is on the sheet, and you read it there.
That is deliberate: pre-extracting every row is what produced an index where 37.8%
of the part codes carried no letter and effective dates were recorded as parts.

1. **Learn the book** - `mcp__catalog__get_catalog_overview` when the vendor is
   unfamiliar. A few hundred tokens on how that publisher organises things, and it
   saves opening the wrong pages. Optionally `mcp__catalog-docs__list_catalogs_parsed`
   to see which books have parsed blocks.
2. **Find the evidence** - Prefer `mcp__catalog-docs__search_blocks` with the part
   number, series or description (and `vendor` / `catalog_id`). Hits include block
   text/html, `bbox`, `file_path`, and `pdf_page`. Read the list price from the
   block when clear; crop with `mcp__pdf-tools__get_page_image(..., region=bbox)`
   only when unclear.
3. **Fallback page index** - If parse is incomplete or search_blocks is empty,
   `mcp__catalog__find_pages` with the part number, series or description, and a
   `vendor` filter. Always pass the vendor; a library-wide search is noisier.
   Then `mcp__pdf-tools__extract_tables` on the `pdf_page` from the hit.
4. **Multiplier** - `mcp__catalog__get_multiplier`. Hager prices **by product
   category**, so pass the category (`locks`, `door_controls`, `exit_devices`,
   `architectural_hinges`, `electrified_products`, ...). Other vendors carry a
   single tier. Special-net text on a PDF sheet: catalog-docs
   `source=multiplier`.
5. **Give up cleanly.** No page, or a page that turns out not to hold the part,
   means MANUAL - not "close enough".

**Cite evidence exactly.** Prefer block `n` + `bbox` + `file_path` from
catalog-docs; otherwise the find_pages `locator` (PDF page and printed page
often differ).

## Applying the multiplier

```
cost = list_price x multiplier
```

Hager example, verified end to end: a 3500-series storeroom lock lists **256.31**;
the locks tier is **0.290** (50/42% discount); cost is **74.33**. At the commodity
margin that is a **101.82** sale each.

**Adders are never included** in a price-book lookup. Electrification, NRP hinges
and premium finishes are added deliberately from
`mcp__reference__get_manual_adders`.

## Vendors with no usable price book

- **Allegion** - not bought direct. Banner Solutions or SecLock, manual entry.
- **Zero, Alarm Lock, Cal-Royal, Dorma** - outside the Phase-1 top-10.
- **Bobrick and Gamco** - priced from HP program NET sheets (2017), not list x
  multiplier. The sheets are old; verify before quoting.
- **Scranton** - access lost. Out of scope entirely.

## Reference data

- @.claude/memory/vendor_tiers.md
- @.claude/memory/cost_sourcing_rules.md

## Worked example

There is no script. `search_pricebook.py` was deleted with the extraction index
it queried; the catalog MCP server replaced it, and the price now comes off the
page rather than out of a table nobody checked.

```
mcp__catalog__find_pages(query="3510 lock", vendor="hager")
  -> file_path "pricebooks/hager_price_book_18.pdf", pdf_page 297,
     locator "PDF p297 (printed p23)", has_prices true

mcp__pdf-tools__extract_tables(file_path=..., pages="297")
  -> the row, and the list price on it

mcp__catalog__get_multiplier(vendor="hager", tier="locks")
  -> 0.290, effective 2026-03-02
```

Pass `file_path` and `pdf_page` exactly as `find_pages` returned them. The books
are not under the project's uploads, and a run that guessed that directory found
the right page and could not open it.

## Output

Quote the `locator` verbatim - it carries the PDF page and the number printed on
the page, and they differ on most pages because section numbering restarts. With
the file name, the multiplier tier and its effective date, that is the full
provenance chain NFR-3 requires.
