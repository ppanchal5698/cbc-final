---
name: price-line-item
description: >
  Prices one quote line by choosing between the three CBC cost paths - P21 last-PO,
  vendor list price x multiplier, or distributor/vendor-RFQ manual entry - honouring
  the freshness rule and recording the source used. Use in Phase 4 of a CBC bid,
  once an opening has been matched to a product.
---

# Price a Line Item

Only three cells are human per line: **Quantity**, **Our Cost**, **Margin**.
This skill produces the middle one.

## Decision tree

```
Is the item on special pricing, or regularly bought?
├── YES -> PATH 1: P21 last-PO price
│          mcp__p21-connector__lookup_last_po (always call; continue if empty)
│          Then mcp__p21-connector__check_freshness on the PO date.
│          Usable only if sold < ~6 months AND no price increase since. (~9/10 right)
│          NEVER read the P21 supplier-list or supplier-cost fields.
│          P21 unreachable -> falls through to PATH 2 or PATH 3.
│
├── Is it a top-10 vendor CBC buys DIRECT (not Allegion distributor)?
│   └── YES -> PATH 2: list x multiplier
│              mcp__catalog__find_pages -> mcp__pdf-tools__extract_tables (price + page)
│              mcp__catalog__get_multiplier (category + effective date)
│              mcp__calc-engine__calculate_line / apply_margin
│              cost = list x multiplier; cost must be non-null on the line
│              Then add any applicable ADDERS - they are never in the lookup.
│
└── OTHERWISE -> PATH 3: distributor lookup or vendor RFQ
               Allegion (Von Duprin, LCN, Schlage, IVES) via Banner/SecLock:
                 cost_source = MANUAL, prompt "price may be out of date - refresh"
               Other distributor-bought (J2, Pionite, Wilsonart):
               Custom / never-sold / special-prep:
                 cost_source = VENDOR_RFQ, status "awaiting vendor quote"
```

## Freshness rule (Path 1)

| Age of the PO | Verdict |
|---|---|
| under ~6 months | fresh - usable if no price increase |
| more than 6 months | unreliable - re-verify before quoting |
| more than 3 years | discard - do not quote from it |

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

At the manual cut-off, emit `cost: null`, `cost_source: "MANUAL"`,
`confidence: 0.0` and a plain-language reason. Do not extrapolate a price from a
similar SKU. There is no partial credit for a confidently wrong price.

## Reference data

- @.claude/memory/cost_sourcing_rules.md
- @.claude/memory/vendor_tiers.md
- @.claude/memory/manual_cutoff.md
- `references/cost_paths.md`
