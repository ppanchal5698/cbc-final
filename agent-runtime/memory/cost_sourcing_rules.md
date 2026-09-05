# Cost Sourcing Rules — the three paths

Cost is sourced by one of exactly three paths. **Record which path was used, and the date,
on every line** (NFR-3 auditability).

## Path 1 — P21 last purchase-order price
For regularly bought items, cost = the **LAST PO price** from purchase history or the
cost screen.

- **Do NOT trust the P21 "supplier list" / "supplier cost" fields** — purchasing does not
  reliably update them.
- Valid when the item was **sold within the last ~24 months and there has been no price increase**.
  This is right about **9 times out of 10**.
- Special-priced items already carry their cost in P21.
- Access is **READ-ONLY**, no write-back (NFR-5, see the p21-read-only rule).

### Freshness rule
| Age of cost | Status |
|---|---|
| under ~24 months | fresh |
| more than 24 months | **unreliable** — re-verify |
| more than 2.5 years | **discard** — do not use |

### Known P21 risk
P21 item IDs often **differ from manufacturer part numbers**, and semi / custom items
will not match at all. **Manual entry must always be available.**

## Path 2 — list price x multiplier
When the item is not on special pricing: **cost = manufacturer list price x CBC tier
multiplier**. See [[vendor_tiers]] for the live multipliers.
Remember the **adders** that are not cleanly in the price book: electrification,
non-removable-pin (NRP) hinges, premium / lead-time finishes.

## Path 3 — distributor lookup or vendor RFQ
Triggered by: **custom sizes** (e.g. 9-ft doors), **unusual preps**, **options not sold in
years** (e.g. electric latch retraction in a given model/size/finish), never-sold-direct
parts, or distributor-only lines.

- **Distributor-bought** (Banner Solutions, SecLock — Allegion; J2 — accessories;
  Pionite, Wilsonart — laminate): **manual price entry required**, always shown with a
  **"price may be out of date — refresh"** prompt (NR-2).
- **Vendor RFQ**: mark the line "awaiting vendor quote", capture the returned price by hand,
  slot it into the draft (FR-16).
- Otherwise check the **manufacturer website** for never-sold-direct parts.

## Sourcing rationale (Matrix 6.5)
Record **how** each item will be sourced — buy direct vs buy through a wholesaler or
distributor — and why. Internal teams and the customer use this to understand pricing
drivers and customizations. The primary source is recorded in P21.

## Direct-equal substitution (Matrix 6.4)
When a drawing specs a function with no named manufacturer, or a specified line is
unavailable, propose the closest of the **top 2-3 brands** (estimator judgment, usually
Hager) and **attach a note explaining the substitution**. Then price via Path 2.

See [[margin_sheet]], [[manual_cutoff]].
