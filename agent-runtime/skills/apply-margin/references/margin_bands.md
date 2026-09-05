# Margin Bands

Read `reference-library/margins/margin_framework.json` via seed only for humans;
agents must use `mcp__reference__get_margin_bands` for every product-type
band, divisor, and accessory derivation. Do not copy the numbers into this file.

Source: Requirements Matrix 6.1, confirmed in the 14 Jul estimator session.

## Accessories: use the JSON, not the original 35% note

The original documentation recorded restroom accessories at 35%. The estimator
session corrected the derivation. The value in `margin_framework.json` is
authoritative.

## Overridable, by design

Margin is an editable default. It is overridden on essentially every quote based
on sourcing:

- **Wendys** - special margin when the product is bought via Banner Solutions or
  SecLock at a higher cost. Exact value PENDING from CBC (NR-9).
- **Distributor buys** generally - higher cost in, lower margin out.
- **Lead time** and genuinely custom first builds - hand-entered margin.

Record the reason every time. An unexplained below-band margin is what the flag
exists to catch.

## Worked example, end to end

Hager 3500-series storeroom lock. Apply the commodity band from
`reference-library/margins/margin_framework.json` via `apply_margin` — do not
hand-compute the divisor.

| Step | Value | Source |
|---|---|---|
| List price | 256.31 | Price Book #18, page 297 |
| Multiplier (locks tier) | 0.290 | Hager discount sheet, effective 2026-03-02 |
| Cost | 74.33 | list x multiplier |
| Band | commodity | margin_framework.json |
| Sale $ EA / Ext | from calc-engine | cost, qty, band |

## Governance

Below-band lines are FLAGGED, never blocked. Approval routing is deferred
(NFR-8 / Matrix 6.7) - there is no margin deviation today and estimators hold to
the standard bands. Revisit when the estimating team grows.
