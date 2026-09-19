# Phase 3b — FRP take-off

Measures fibreglass-reinforced-panel wall coverage off the drawings. Runs
concurrently with Phases 3 and 3c, only where FRP is specified.

| | |
|---|---|
| **Agent** | `frp-specialist` (haiku) |
| **Job type** | part of `extract_bid_set`; the `frp` leg of the take-off wave |
| **Script** | `bash workflows/phase3b_frp.sh <project>` |
| **Skill** | `frp-takeoff` |
| **Writes** | `extracted/frp_takeoff.json` — schema-gated |

## Inputs

`extracted/scope_summary.json` — FRP must be in scope — and the drawings.

## What happens

Geometry first, quantities second:

1. Product type and manufacturer as specified (Nudo is the usual one; it has a
   catalog under `data/pricebooks/catalogs/catalog_nudo.md`).
2. Location, and the drawing or Vu360 scale being measured at.
3. **Perimeter linear feet** of the walls receiving panel.
4. **Inside and outside corner counts** — these drive trim, not panel, and are
   counted separately for that reason.
5. Wall height.
6. Panel, trim and adhesive notes from the drawings.

## Quantities stay null until the constants exist

`mcp__reference__get_frp_constants` returns CBC's conversion constants —
linear feet and height to panel count, corner count to trim, coverage to
adhesive.

**Those constants are currently `PENDING`**
(`data/reference-library/frp_constants/conversion_constants.json`). Until an
estimator supplies them, this phase records the geometry and leaves the material
quantities **null and flagged**. It does not invent a conversion.

That is the correct behaviour under NFR-2: a measured perimeter with no panel
count is an honest artifact; a panel count derived from a guessed constant is a
wrong number that looks right.

## Tools

`mcp__bid-docs__*` to find the elevations and plans ·
`mcp__pdf-tools__get_page_image` / `get_page_size` / `extract_text` /
`find_sheets` to measure · `mcp__reference__get_frp_constants` ·
`mcp__artifact-storage__save_artifact`.

`get_page_size` matters here more than elsewhere: a measurement is only
meaningful against the page frame it was taken in, and `page_size` is recorded
alongside `bbox` for exactly that reason.

## Output

`extracted/frp_takeoff.json`, validated against `frp_takeoff.schema.json`. Not
in the blocking set — a failure warns rather than stopping the pipeline, because
FRP is a subset of most bids rather than the spine of one.

## Handoff

[Phase 4](phase-4-pricing.md) prices the FRP block separately from the door
lines, and the quotation keeps it as its own section.
