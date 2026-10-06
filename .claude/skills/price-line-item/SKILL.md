---
name: price-line-item
description: >
  Prices one quote line by choosing between CBC cost paths - P21 last-PO,
  special net, product catalog (catalogItems) baseline, vendor list x multiplier,
  or distributor/vendor-RFQ manual entry - honouring the freshness rule and
  recording the source used. Use in Phase 4 of a CBC bid, once an opening has
  been matched to a product.
---

# Price a Line Item

Only three cells are human per line: **Quantity**, **Our Cost**, **Margin**.
This skill produces the middle one.

## Decision tree

`preprice.py` runs this ladder in code before the pricing pass, in this order; it
is your manual procedure for a line the seed left unpriced. A rung whose price
sheet has lapsed is skipped and the next one tried.

```
Is it an Allegion brand (Von Duprin, LCN, Schlage, IVES)?
├── YES -> cost_source = DISTRIBUTOR_MANUAL, cost null, reason names Banner/SecLock.
│          Stop - no other rung is tried, even when IVES is in the Hager book.
│
Is the item on special pricing, or regularly bought?
├── YES -> PATH 1: P21 last-PO price
│          mcp__p21-connector__lookup_last_po (continue if empty; the seed skips
│          it without a call when P21 is not configured)
│          Then mcp__p21-connector__check_freshness on the PO date.
│          Usable only while fresh AND no price increase since.
│          NEVER read the P21 supplier-list or supplier-cost fields.
│          P21 unreachable -> falls through.
│
├── Special net on multiplier sheet?
│   └── YES -> mcp__catalog__get_special_net
│              cost_source = SPECIAL_NET (do not multiply again)
│              cite item code / special-net in cost_source_detail
│
├── Product catalog (catalogItems) row?
│   └── YES -> **Always call before PDFs:** mcp__catalog__lookup_catalog_item(part, vendor?)
│              Curated seed / hand-added only (never PDF ingest).
│              cost_source = CATALOG_BASELINE or SPECIAL_NET; cite product catalog
│              Or LIST_X_MULTIPLIER from returned list×multiplier + cite catalog
│
├── Is it a top-10 vendor CBC buys DIRECT (not Allegion distributor)?
│   └── YES -> PATH 2: list x multiplier from PDF (only if catalog miss)
│              Use `file_path` from find_pages exactly (repo-relative is OK).
│              mcp__catalog__find_pages -> mcp__pdf-tools__extract_tables / extract_text
│              Threshold pages: read NGP list column + Pemko comparison numbers.
│              If table text is unclear: mcp__pdf-tools__get_page_image(page_number=…, region=bbox).
│              mcp__catalog__get_multiplier (category + effective date)
│              mcp__calc-engine__cost_from_list then apply_margin
│              cost = list x multiplier; **cost, sale_ea, ext_price must be non-null**
│              Never tag LIST_X_MULTIPLIER or set multiplier under MANUAL.
│              Then add any applicable ADDERS - they are never in the lookup.
│
└── OTHERWISE -> PATH 3: distributor lookup or vendor RFQ
               Other distributor-bought (J2, Pionite, Wilsonart):
                 cost_source = DISTRIBUTOR_MANUAL, prompt "price may be out of date - refresh"
               Custom / never-sold / special-prep:
                 cost_source = VENDOR_RFQ, status "awaiting vendor quote"
               Anything else no rung answered:
                 cost_source = MANUAL, with the reason
```

A `MANUAL`, `VENDOR_RFQ` or `DISTRIBUTOR_MANUAL` line with no cost blocks
proposal approval until the estimator prices it.

## Freshness rule (Path 1)

A PO is fresh, unreliable (re-verify before quoting) or discarded by age. The
windows are owned by `apps/backend/src/cbc/modules/ops/api/freshness_rules.py`
and the app's Freshness settings; `mcp__p21-connector__check_freshness` returns
the verdict - do not judge the age yourself.

## Adders (Path 2)

Apply via `mcp__calc-engine__cost_from_list` — adders go on the **list** price,
then the multiplier applies to the sum. Sources: `mcp__reference__get_manual_adders`.

## Lite kits (NR-1)

For lites/louvers: `mcp__calc-engine__lookup_lite_kit_list_price`, then
`cost_from_list` with the vendor multiplier.

## What must be recorded on every line

`cost`, `cost_source`, `cost_source_detail`, `multiplier`, `multiplier_tier`,
`multiplier_effective_date`, `price_book_version`, `source_page`, `priced_at`,
and the **sourcing rationale** - buy direct vs buy through a wholesaler, and why
(Matrix 6.5). Without these the line is not auditable (NFR-3).

## When to stop

At the manual cut-off, emit `cost: null`, `cost_source: "MANUAL"` (or
`"DISTRIBUTOR_MANUAL"` for a distributor-bought line), `confidence: 0.0` and a
plain-language reason. Do not extrapolate a price from a similar SKU. There is
no partial credit for a confidently wrong price.

## Reference data

- @.claude/memory/cost_sourcing_rules.md
- @.claude/memory/vendor_tiers.md
- @.claude/memory/manual_cutoff.md
- `references/cost_paths.md`
