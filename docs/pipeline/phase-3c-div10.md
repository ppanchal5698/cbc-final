# Phase 3c — Division 10 specialties

Counts toilet partitions, restroom accessories, washroom equipment and hand
dryers. Runs concurrently with Phases 3 and 3b, only when
`scope_summary.div10_in_scope` is true.

| | |
|---|---|
| **Agent** | `div10-specialist` (haiku) |
| **Job type** | part of `extract_bid_set`; the `div10` leg of the take-off wave |
| **Script** | `bash workflows/phase3c_div10.sh <project>` |
| **Skill** | `extract-div10-takeoff` |
| **Writes** | `extracted/div10_takeoff.json` — schema-gated |

## Inputs

`extracted/scope_summary.json` with `div10_in_scope: true`, plus the drawings
and the Division 10 specification sections Phase 2 located.

## What happens

Per item: **product type, manufacturer, location or drawing reference, and
count.** Counts come off the plans; types and manufacturers come off the
specification. Where the two disagree, open the page and record which one you
read.

Four families:

| Family | Typical vendors |
|---|---|
| Toilet / restroom partitions | ASI, Bradley — **not Scranton Products** |
| Restroom accessories | ASI, Bobrick, Bradley, Gamco |
| Washroom equipment | — |
| Hand dryers | World Dryer, Excel XLERATOR — **not American Dryer** |

Catalogs for all of these are under `data/pricebooks/catalogs/`
(`catalog_asi.md`, `catalog_bobrick.md`, `catalog_bradley.md`,
`catalog_gamco.md`, `catalog_world_dryer.md`).

## Two vendors that are out

Both are scope rules, not preferences, and both belong in
`out_of_scope_items` if specified:

- **Scranton Products** — access was lost; sourcing it would mean a costlier
  distributor.
- **American Dryer** — no longer used. Offer World Dryer or Excel XLERATOR
  instead, with a substitution note naming what was specified and what is being
  offered.

JL Industries access doors and specialties are not CBC estimating at all.

## Tools

`mcp__bid-docs__list_documents` · `get_outline` · `search_blocks` ·
`get_page_blocks` — find the Division 10 sections and the restroom plans.

`mcp__pdf-tools__extract_tables` · `extract_text` · `get_page_image` ·
`find_sheets` · `get_page_size` — read and count.

`mcp__artifact-storage__save_artifact`.

## Counting is where this phase goes wrong

A count is the one field with no notation to fall back on — if the plan is
ambiguous, there is nothing to cross-check it against. So the verify-before-
present gate applies to every count that is not plainly legible: open the page,
crop it with `get_page_image(region=bbox)` if the text layer is unclear, and
record what you read in `evidence_note`. A count below 0.75 confidence is
flagged, not rounded.

## Output

`extracted/div10_takeoff.json`, validated against `div10_takeoff.schema.json`.
Not in the blocking set — a failure warns.

## Handoff

[Phase 4](phase-4-pricing.md). Restroom accessories are priced and presented as
their own block in the quotation, separate from the door lines.
