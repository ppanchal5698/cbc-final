# The Three Cost Paths

## Path 1 - P21 last purchase-order price

**Use when:** the item is regularly bought or carries special pricing in P21.

- Cost = the **LAST PO price**, from purchase history or the cost screen.
- **Never** the "supplier list" or "supplier cost" fields - purchasing does not
  keep them current. This is the single most important trap on this path.
- Right about **9 times out of 10** when the item sold within the last ~24 months with
  no price increase since.
- Access is **READ-ONLY** (NFR-5).

**Freshness:**

| Age | Status | Action |
|---|---|---|
| < ~24 months | fresh | usable |
| more than 24 months | unreliable | re-verify against the vendor sheet |
| more than 2.5 years | stale | discard |

**Known risks:** P21 item IDs frequently differ from manufacturer part numbers,
and semi/custom items will not match at all. Manual entry must always be
available. P21 integration feasibility is still open (NR-10) - today every lookup
returns a structured "manual entry required" response.

`cost_source: "P21_LAST_PO"`, `cost_source_detail: "PO 2026-03-14"`

---

## Path 2 - vendor list price x multiplier

**Use when:** the item is not on special pricing and the vendor is one of the
top-10 with a price book on file.

```
cost = manufacturer list price x CBC multiplier tier
```

The multiplier is a **per-vendor account attribute**, not a per-item value. MAP is
not cost. Price changes arrive as dated memos with a protection window.

**Hager prices by product category** - use the right one:

| Category | Multiplier | Discount |
|---|---|---|
| Locks | 0.290 | 50/42% |
| Door controls | 0.300 | 50/40% |
| Exit devices | 0.300 | 50/40% |
| Electrified products | 0.410 | 50/18% |
| Auto operators | 0.400 | 50/20% |
| Architectural hinges | 0.210 | 50/58% |
| Residential hinges | 0.375 | 50/25% |

Single-tier vendors: ASI 0.375, National Guard 0.45, Rockwood accessories 0.55,
Bradley 0.53, World Dryer L3 0.339.
Net-sheet vendors (not list x multiplier): Bobrick, Gamco.

**Worked example:** Hager 3500-series storeroom lock, list 256.31, locks tier
0.290, cost **74.33**.

`cost_source: "LIST_X_MULTIPLIER"`, plus `multiplier`, `multiplier_tier`,
`multiplier_effective_date`, `price_book_version`, `source_page`.

---

## Path 3 - distributor lookup or vendor RFQ

**Use when:** the item is distributor-bought, custom, never sold, or specially
prepped.

### 3a - distributor manual entry (NR-2)

| Distributor | Lines |
|---|---|
| Banner Solutions, SecLock | Allegion - Von Duprin, LCN, Schlage, Ives |
| J2 | restroom accessories |
| Pionite, Wilsonart | laminate |

Requires **manual price entry** and always displays
**"price may be out of date - refresh"**.

`cost_source: "DISTRIBUTOR_MANUAL"`

### 3b - vendor RFQ (FR-16)

Triggered by custom sizes (e.g. 9-ft doors), unusual preps, options not sold in
years (e.g. electric latch retraction in a given model/size/finish), and
never-sold-direct parts.

Mark the line `awaiting vendor quote`, capture the returned price by hand, slot it
into the draft. This can hold up a bid - surface it early in the review summary,
not at the end.

`cost_source: "VENDOR_RFQ"`

---

## Sourcing rationale (Matrix 6.5)

Record on every line **how** the item will be sourced - buy direct vs buy through
a wholesaler or distributor - and why. Internal teams and the customer use this to
understand pricing drivers and customizations. The primary source is recorded in
P21.
