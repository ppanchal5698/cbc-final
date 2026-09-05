# Data Stewardship (NFR-10) — **STATUS: OPEN**

Each pricing source needs a **named owner and a refresh cadence** so automated quotes never
run on stale data. **Neither has been assigned yet** (Open Item 15) — this rule records the
gap rather than papering over it.

## Sources that need an owner and a cadence
| Source | Path | Owner | Cadence |
|---|---|---|---|
| Reference library | reference-library/ | **UNASSIGNED** | **UNDEFINED** |
| Vendor multiplier sheets | pricebooks/ | **UNASSIGNED** | **UNDEFINED** |
| Margin sheet | reference-library/margins/ | **UNASSIGNED** | **UNDEFINED** |
| Top-10 stock list | reference-library/hardware_sets/ | **UNASSIGNED** (CBC to provide, NR-6) | **UNDEFINED** |

## What the Ops-Hub changed
Staleness is now **visible to the person who can act on it**, not just to a log:

- The price-books screen shows every program with its age, and flags anything past
  ~24 months or carrying no effective date at all.
- The rail badge carries the stale count on every screen.
- `catalog.list_price_books` returns `ageDays` and `stale`, so a pricing pass sees
  the same signal the estimator does.
- Purchasing can record a review date and upload a newer sheet in one place.

**None of this assigns an owner or a cadence.** The gap is unchanged; it is merely
harder to miss. NFR-10 stays OPEN until CBC names a person and an interval.

## Interim mitigation
- Every price-book file carries its **effective date** in pricebooks/index.json and that date
  is echoed onto every priced line (see the auditability rule).
- scripts/refresh_pricebooks.sh reports the age of each price book and warns past **~24 months**.
- Manually entered prices always show the **"price may be out of date — refresh"** prompt (NR-2).
- The P21 freshness rule (more than 24 months unreliable, more than 2.5 years discard) applies independently.

## Risk if left open
Stale price sheets drive wrong quotes — silently, and at scale.

## Owner
CBC Purchasing and Estimating. **Still to be named.**
