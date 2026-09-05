---
name: apply-margin
description: >
  Applies the CBC product-type margin framework as an editable default per line,
  computes Sale $ EA = Cost / (1 - margin), and flags any line below its band
  floor. Handles sourcing-driven overrides such as special-customer margins and
  distributor buys. Use in Phase 4 after a line has a cost.
---

# Apply Margin

## The bands

Use `mcp__reference__get_margin_bands` (or `mcp__calc-engine__validate_margin`).
Mongo `referenceData/margins` is the live source of truth — do not Read seed JSON
under `reference-library/` and do not invent band numbers.

Stable for about 14 years.

## The formula

```
Sale $ EA = Cost / (1 - margin)
Unit      = Sale $ EA
Ext       = Unit x Qty
Sub-total = SUM(Ext) per group
Grand tot = SUM(sub-totals)
```

Use `mcp__calc-engine__apply_margin` and `mcp__calc-engine__compute_totals` -
do not compute this by hand anywhere else in the pipeline.

There is **no unit-weight column**. It was legacy from truck-loading and was
removed.

## Classifying a line

| Line | Band |
|---|---|
| Hollow metal frame, door, standard hardware | commodity |
| Toilet partitions, urinal screens | restroom_partitions |
| Laminated doors, specialty assemblies | specialty |
| Anything from an outside fabricator, custom sizes | custom_built |
| Grab bars, mirrors, dispensers, hand dryers | accessories |

When a line could sit in two bands, take the **lower margin** and note it. Do not
silently pick the more profitable one.

## Overrides

Margin is an editable default, overridden on essentially every quote by sourcing:

- **Special-customer margins** - e.g. Wendy's. Use
  `mcp__reference__get_special_customer_margin`. Values are still
  PENDING from CBC (NR-9), so an override here is a prompt to the estimator, not
  an automatic adjustment.
- **Distributor buys** - purchasing through Banner Solutions or SecLock at higher
  cost typically **drops** the margin.
- **Lead time and custom first builds** - hand-entered margin.

**Always record `override_reason`.** A below-band margin with no recorded reason
is exactly what the governance flag is for.

## Governance - flag, never block

`mcp__calc-engine__validate_margin` returns pass/fail against the band floor. A
fail is written to `review/review_flags.json` at severity `medium`. Nothing is
routed for approval - NFR-8 is deferred, because there is no margin deviation
today and approval routing only matters with more estimators.

## Reference data

- @.claude/memory/margin_sheet.md
- `references/margin_bands.md`

## Output

Write to `projects/{project}/priced/margin_applied.json`: one record per line with
`product_type`, `default_margin`, `applied_margin`, `overridden`,
`override_reason`, `sale_ea`, `ext_price`, `margin_check`.
