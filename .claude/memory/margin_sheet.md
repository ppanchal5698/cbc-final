# Margin Framework

Margin is applied **by product type, as a divisor**. The framework has been stable ~14 years.

Bands, divisors, and accessory derivation live in
`reference-library/margins/margin_framework.json`. Do not copy the numbers here.

## Formula (the only money math in the system)

    Sale $ EA = Cost / (1 - margin)     # equivalently Cost / divisor
    Unit      = Sale $ EA
    Ext       = Unit x Qty
    Sub-total = Sale $ EA x Qty
    Grand tot = SUM(sub-totals)

Only **three** cells are human per line: **Quantity**, **Our Cost**, **Margin**.
Everything to the right is computed.

**Legacy "unit weight" is removed** — it dates from truck-loading years ago and is not used.

## Overridable
Margin is an **editable default and is overridden on essentially every quote based on
sourcing**:
- Special-customer margins, e.g. **Wendy's** — see
  reference-library/multipliers/special_customer_margins.json
- If an item is bought through a distributor (Banner Solutions, SecLock) at a higher cost,
  the margin drops.
- Lead time and sourcing move the margin. Genuinely custom first-builds get a hand-entered margin.

## Governance
Margin-approval routing is **out of scope for now** (NFR-8 / Matrix 6.7). There is no margin
deviation today — estimators hold to standard margins. Below-band lines are still *flagged*
(FR-15) but nothing is routed for approval. Revisit when the team grows.

See [[cost_sourcing_rules]], [[manual_cutoff]].
