# Cost Sourcing Rules — the cost ladder

Cost comes from the first rung of a ladder that answers. **Record which rung was used, and
the date, on every line** (NFR-3 auditability). `preprice.py` runs the ladder in code
before the pricing pass, in this order (see `.claude/guides/pricing.md`):

0. **Allegion check** — Allegion brands are `DISTRIBUTOR_MANUAL`, cost null; no rung is tried.
1. **P21 last PO** (`P21_LAST_PO`) — skipped, with no network call, when P21 is not configured.
2. **Special net** (`SPECIAL_NET`) — Hager's special-net sheet; already the cost.
3. **Product catalog baseline** (`CATALOG_BASELINE`) — a curated `catalogItems` row.
4. **List × multiplier** (`LIST_X_MULTIPLIER`).
5. **`MANUAL`** with a reason, or `VENDOR_RFQ` once a quote is requested.

A lapsed price sheet is skipped and the next rung tried. The sections below are the
business rules behind the rungs.

## Path 1 — P21 last purchase-order price
For regularly bought items, cost = the **LAST PO price** from purchase history or the
cost screen.

- **Do NOT trust the P21 "supplier list" / "supplier cost" fields** — purchasing does not
  reliably update them.
- Valid when the item was **sold within the P21 freshness window and there has been no price
  increase** (the window is stated under *Values in force* in a run's brief; see the
  Freshness rule below). This is right about **9 times out of 10**.
- Special-priced items already carry their cost in P21.
- Access is **READ-ONLY**, no write-back (NFR-5, see `.claude/guides/pricing.md`).

### Freshness rule
A PO cost is **fresh**, **unreliable** (re-verify) or **discarded** by age (Matrix 6.2).
The windows are owned by `apps/backend/src/cbc/modules/ops/api/freshness_rules.py` and
the app's Freshness settings; `mcp__p21-connector__check_freshness` applies them.

### Known P21 risk
P21 item IDs often **differ from manufacturer part numbers**, and semi / custom items
will not match at all. **Manual entry must always be available.**

## Special net and product catalog
A **special net** from a vendor's multiplier sheet is already the cost — never multiply it
again. A curated **product catalog** (`catalogItems`) row is tried before any price-book
page, so a part the catalog holds is never re-read off a PDF.

## Path 2 — list price x multiplier
When nothing above answered: **cost = manufacturer list price x CBC tier
multiplier**. The live multipliers come from `mcp__catalog__get_multiplier`; see
[vendor_tiers](vendor_tiers.md) for the account context.
Remember the **adders** that are not cleanly in the price book: electrification,
non-removable-pin (NRP) hinges, premium / lead-time finishes.

## Path 3 — distributor lookup or vendor RFQ
Triggered by: **custom sizes** (e.g. 9-ft doors), **unusual preps**, **options not sold in
years** (e.g. electric latch retraction in a given model/size/finish), never-sold-direct
parts, or distributor-only lines.

- **Distributor-bought** (Banner Solutions, SecLock — Allegion; J2 — accessories;
  Pionite, Wilsonart — laminate): `cost_source: DISTRIBUTOR_MANUAL`, **manual price entry
  required**, always shown with a **"price may be out of date — refresh"** prompt (NR-2).
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

See [margin_sheet](margin_sheet.md), [manual_cutoff](manual_cutoff.md).
