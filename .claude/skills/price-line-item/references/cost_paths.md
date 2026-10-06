# The Cost Paths

The order is the ladder `preprice.py` runs in code: **Allegion check** (→ 3a,
`DISTRIBUTOR_MANUAL`, no other path tried) → **P21 last PO** (skipped with no
call when P21 is not configured) → **special net** → **product catalog
baseline** → **list × multiplier** → **3a/3b or `MANUAL`** with a reason. A path
whose price sheet has lapsed is skipped and the next one tried. The sections
below are numbered by their history, not their order.

## Path 1 - P21 last purchase-order price

**Use when:** the item is regularly bought or carries special pricing in P21.

- Cost = the **LAST PO price**, from purchase history or the cost screen.
- **Never** the "supplier list" or "supplier cost" fields - purchasing does not
  keep them current. This is the single most important trap on this path.
- Right about **9 times out of 10** when the item sold within the P21 freshness
  window (stated under *Values in force* in your brief; see **Freshness** below)
  with no price increase since.
- Access is **READ-ONLY** (NFR-5).

**Freshness:** fresh (usable), unreliable (re-verify against the vendor sheet) or
stale (discard). `mcp__p21-connector__check_freshness` returns the verdict from
the windows in `apps/backend/src/cbc/modules/ops/api/freshness_rules.py` and the
app's Freshness settings.

**Known risks:** P21 item IDs frequently differ from manufacturer part numbers,
and semi/custom items will not match at all. Manual entry must always be
available. P21 integration feasibility is still open (NR-10) - today every lookup
returns a structured "manual entry required" response.

`cost_source: "P21_LAST_PO"`, `cost_source_detail: "PO 2026-03-14"`

---

## Path 1b - special net

**Use when:** `get_special_net` returns a fixed net for the part (Hager
multiplier sheet / curated nets). That number **is** cost — do not apply a
category multiplier again.

`cost_source: "SPECIAL_NET"`, cite item code / special-net provenance in
`cost_source_detail`.

---

## Path 2b - product catalog baseline

**Use when:** before opening a PDF (or when PDF page search would miss) and
`lookup_catalog_item` finds a curated `catalogItems` row (seedSource cites
catalog.md, or hand-added). Never use price-book ingest extracts this way.

`cost_source: "CATALOG_BASELINE"` (or `SPECIAL_NET` when the row is a net),
`cost_source_detail` must cite the product catalog / seedSource.

---

## Path 2 - vendor list price x multiplier

**Use when:** the item is not on special pricing and the vendor is one of the
top-10 with a price book on file.

```
cost = manufacturer list price x CBC multiplier tier
```

The multiplier is a **per-vendor account attribute**, not a per-item value. MAP is
not cost. Price changes arrive as dated memos with a protection window.

**Hager prices by product category** - use the right one. The multiplier for
each comes from `mcp__catalog__get_multiplier(vendor="hager", category=...)`
with its effective date; none is written here, because a copy drifts from the
sheet purchasing maintains.

| Category | `category` |
|---|---|
| Locks | `locks` |
| Door controls | `door_controls` |
| Exit devices | `exit_devices` |
| Electrified products | `electrified_products` |
| Auto operators | `auto_operators` |
| Architectural hinges | `architectural_hinges` |
| Residential hinges | `residential_hinges` |

Single-tier vendors (`get_multiplier` with the vendor alone): ASI, National
Guard, Rockwood accessories, Bradley, World Dryer L3.
Net-sheet vendors (not list x multiplier): Bobrick, Gamco.

**Worked example:** Hager 3500-series storeroom lock, list 256.31; cost is that
list x the `locks` multiplier from `get_multiplier`, computed by
`cost_from_list`.

**Hager thresholds & weatherstrip:** architect schedules often specify **Pemko**
or **Zero** catalog numbers (e.g. 275A, 39A). Hager Price Book #18 threshold
pages list **NGP codes** (401S, 402S, …) with a **Pemko comparison-number**
column — read the **NGP list price**, not a text search for 275A. When
`lookup_catalog_item` misses, use `find_pages` → `get_page_blocks` or
`get_page_image(region=bbox)` on the table block, then `get_multiplier` with
category `thresholds_weatherstrip`. Never write `multiplier` under
`cost_source: MANUAL` — either finish with a non-null `cost` or stay MANUAL
without book metadata.

`cost_source: "LIST_X_MULTIPLIER"`, plus `multiplier`, `multiplier_tier`,
`multiplier_effective_date`, `price_book_version`, `source_page`. Cite a PDF
`file_path`+locator **or** the product catalog when the list came from Path 2b.

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
