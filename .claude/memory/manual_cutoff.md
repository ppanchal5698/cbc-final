# The Manual Cut-off (NR-13 — design principle)

**Automate the stock / top-N items. Beyond that, stop.**

> Do NOT attempt to price every option permutation. The estimator handles the long tail.

## What is automated (Phase 1)
- The **top-10 vendors** — 90%+ of quote volume. See [[vendor_tiers]].
- The **top-10 stock items per product type** (locks, exits, closers, hinges, kick plates,
  thresholds, sweeps, weatherstrip, silencers). Grade variants push this to roughly 20.
- Quoting is by **part number / series**, not by grade — e.g. Hager 3400 vs 3500 is
  grade 1 vs grade 2. Architects specify by part number/series, so match on that.

## What stays MANUAL — hard cut-off
- **Custom sizes** (e.g. 9-ft doors)
- **Unusual preps**
- **Options not sold in years** (e.g. electric latch retraction in a given model/size/finish)
- **Distributor-bought lines** (Banner, SecLock, J2, Pionite, Wilsonart)
- Anything with **no catalog price**
- The full option matrix — function, backset, finish, lever, keyway, strike, electrified —
  lives in the **CUSTOM / OTHER tab**, not in the automated picker

## How to behave at the cut-off
Do not guess, do not extrapolate a price from a similar SKU, do not silently pick the
nearest stock item. **Emit the line with cost_source "MANUAL", confidence 0.0, and a
plain-language reason**, and let the estimator price it.

There is no partial credit for a confidently wrong price.

See [[cost_sourcing_rules]], the accuracy-trust rule.
