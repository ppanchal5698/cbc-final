# Phase 4 — Matching and pricing

Turns extracted openings into priced lines. Two agents, both on Sonnet, both
doing judgment work: deciding which catalog entry is the specified part, and
deciding where a cost may legitimately come from.

| | |
|---|---|
| **Agents** | `product-matcher`, then `pricing-engineer` — both **sonnet** |
| **Job type** | `match_and_price` |
| **Script** | `bash workflows/phase4_pricing.sh <project>` |
| **Command** | `/price` |
| **Skills** | `match-hardware-sets`, `scan-product-catalog`, `price-line-item`, `apply-margin` |
| **Writes** | `extracted/hardware_sets.json`, `priced/line_items.json`, `priced/margin_applied.json` |

## Inputs

`extracted/line_items.json`, `extracted/scope_summary.json`, plus
`frp_takeoff.json` and `div10_takeoff.json` where present.

---

## 4a — Matching (`product-matcher`)

Matches every opening and hardware item to the closest reference-library entry,
respecting fire rating, handing, finish, series and manufacturer preference.

**This agent has no `pdf-tools` at all.** That is deliberate: it works from what
Phase 3 extracted. If it needed the drawing again, the take-off was wrong, and
giving it PDF tools would let it quietly redo Phase 3 with none of Phase 3's
verification discipline.

Order of resort:

1. `mcp__catalog__recall_match` — Tier 0, FR-13. What an estimator already
   confirmed for this part, out of `matchLearning`.
2. `mcp__catalog__lookup_catalog_item(part, vendor?)` — curated catalog rows.
3. `mcp__catalog__search_catalog_items(description, vendor?)` — a descriptive
   query reaches parts a part-number lookup cannot.
4. `mcp__catalog-docs__search_blocks` — the parsed price-book text.

`mcp__reference__get_finish_crosswalk` resolves the dual nomenclature (US26D ↔
626) so a finish mismatch is not read as a different part.

**Confidence per match**, and the bands are not advisory:

| Score | Meaning | Action |
|---|---|---|
| 0.95–1.00 | exact part number, all attributes agree | accept |
| 0.75–0.94 | series match, one soft attribute differs | accept with a note |
| 0.40–0.74 | plausible, needs a human | **flag** |
| 0.00–0.39 | no usable match | **flag, price manually** |

`CONFIDENCE_FLOOR = 0.75` lives in
`apps/backend/src/cbc/modules/pricing/api/confidence.py` and may be written
nowhere else — `tests/architecture/test_confidence_floor.py` enforces that,
including in `apps/web/components/extraction/line-item-row.tsx`.

A direct-equal substitution always carries a **substitution note** naming what
was specified and what is being offered instead.

Writes `extracted/hardware_sets.json`.

---

## 4b — Pricing (`pricing-engineer`)

Five cost paths, tried **in order**. The rule is to walk down the list — not to
skip a path without calling it.

**1. P21 last purchase-order price.** Always call
`mcp__p21-connector__lookup_last_po` first, then `check_freshness` on the PO
date. Valid when sold within roughly the last 6 months with no price increase
since — right about nine times out of ten. **Never** read P21's "supplier list"
or "supplier cost" fields; purchasing does not keep them current. Access is
read-only (NFR-5). If P21 is disconnected or has no fresh PO, continue down the
list.

**2. Special net.** `mcp__catalog__get_special_net(vendor, part)`. A hit is
already Our Cost — **do not multiply again**. Tag `cost_source: SPECIAL_NET`.

**3. Product catalog (Path 2b).** `mcp__catalog__lookup_catalog_item` on every
line **before opening any PDF**. Pass the part as the schedule writes it —
`PEMKO-275A-42`, not a token you picked out of it; the tool normalises and
reports what it matched on in `matched_on`, and guessing the token throws that
away. On a miss, `search_catalog_items` before any PDF. Tag `CATALOG_BASELINE`,
or `SPECIAL_NET` when `price_basis` says so.

   A miss from both **is an answer**: the catalog has no row for this vendor,
   which is the case for Allegion (IVES, LCN, Von Duprin, Schlage) and Zero. Go
   to path 5, not to a PDF hunt for a substitute.

**4. List price × multiplier (Path 2).** Only when the catalog misses, and only
for vendors CBC buys direct. `mcp__catalog__find_pages` to locate,
`mcp__catalog-docs__search_blocks` for blocks and bbox, then
`mcp__calc-engine__cost_from_list` with `mcp__catalog__get_multiplier`. Cite the
file, page and bbox verbatim in `cost_source_detail`. Tag
`LIST_X_MULTIPLIER` and record `multiplier_tier` and
`multiplier_effective_date`.

**5. Manual.** At the manual cut-off, emit `cost: null`,
`cost_source: "MANUAL"`, confidence 0.0, and a **plain-language reason** in
`cost_source_detail` — "Allegion, bought through Banner, needs a distributor
quote". Not an error. The estimator prices it.

### Margin

`mcp__calc-engine__apply_margin` against the product-type bands from
`mcp__reference__get_margin_bands`. The band is an **editable default**, not a
floor that blocks. `validate_margin` flags a line below its band into
`review/review_flags.json` at severity medium; it does not route, escalate or
require sign-off — approval routing is explicitly out of scope for this phase.

Legitimate overrides, which are not defects: sourcing changed (bought through a
distributor at higher cost), a special-customer margin applies, or lead time and
a custom first build warrant a hand-entered number. **Record the reason.** A
below-band margin with no recorded reason is what the flag is for.

### Arithmetic

Every calculation goes through `calc-engine`, never by hand.
`calculate_line` → `apply_margin` → `compute_totals`. Rounding happens **once,
at the extension**, and the server's `_demo()` pins the contract: a $74.33 cost
at the commodity band gives `sale_ea = 101.82` and `ext_price = 305.47` across a
quantity of three.

The band rate itself is deliberately not written here. It lives in
`referenceData`, seeded from `data/reference-library/margins/margin_framework.json`
and served by `mcp__reference__get_margin_bands` — prose that restates it is
prose that goes stale, which is what `tests/modules/pricing/test_margin_pointers.py`
checks for.

### Provenance on every line

`cost_source` · `cost_source_detail` · `priced_at` · plus `multiplier_tier` and
`multiplier_effective_date` where path 4 was used, and `price_book_version`
(e.g. "Hager Price Book #18, effective 2026-02-02"). This is NFR-3: months
later, an estimator must be able to answer "where did this number come from?",
and a stale price sheet must be visible as stale rather than silently wrong.

---

## Output

`priced/line_items.json` (validated against `priced_line_items.schema.json`) and
`priced/margin_applied.json`. Both are checkpoints — written with
`save_artifact`, never a bare `Write`.

The worker renders `quotation.html` itself: door-grouped with subtotals, a
separate restroom-accessories block, an FRP block, a TBD freight line and the
grand total. `quote-builder` exists for interactive and headless use but is not
in the orchestrator chain.

## Handoff

[Phase 5](phase-5-review.md) scores what this phase produced and decides what a
human needs to look at.
