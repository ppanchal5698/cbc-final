# Margin Framework

Margin is applied **by product type, as a divisor**. The framework has been stable ~14 years.

Bands, divisors, and accessory derivation are served by `mcp__reference__get_margin_bands`
and edited in the app at `/settings` (seed: `data/reference-library/margins/margin_framework.json`).
Do not copy the numbers here.

## Formula (the margin math; calc-engine owns it)

    Sale $ EA = Cost / (1 - margin)     # equivalently Cost / divisor
    Unit      = Sale $ EA
    Ext       = Unit x Qty
    Sub-total = SUM(Ext) per group
    Grand tot = SUM(sub-totals)

Cost itself (list × multiplier) and sales tax are computed elsewhere in calc-engine.

Only **three** cells are human per line: **Quantity**, **Our Cost**, **Margin**.
Everything to the right is computed.

**Legacy "unit weight" is removed** — it dates from truck-loading years ago and is not used.

## Overridable
Margin is an **editable default and is overridden on essentially every quote based on
sourcing**:
- Special-customer margins, e.g. **Wendy's** — applied in code (`pricing.special_margin`,
  customer then brand) by pre-pricing and by `mcp__calc-engine__apply_margin`; seed:
  `data/reference-library/multipliers/special_customer_margins.json`
- If an item is bought through a distributor (Banner Solutions, SecLock) at a higher cost,
  the margin drops.
- Lead time and sourcing move the margin. Genuinely custom first-builds get a hand-entered margin.

## Governance
Margin-approval routing is **out of scope for now** (NFR-8 / Matrix 6.7). There is no margin
deviation today — estimators hold to standard margins. Below-band lines are *flagged*
(FR-15), and a below-band line with no `margin_override_reason` **blocks proposal approval**
until the estimator records one; with a reason it is advisory. Nothing is routed for
approval. Revisit when the team grows.

See [cost_sourcing_rules](cost_sourcing_rules.md), [manual_cutoff](manual_cutoff.md).
