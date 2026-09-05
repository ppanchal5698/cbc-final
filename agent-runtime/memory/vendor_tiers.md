# Vendor Tiers & Multipliers

Cost for a non-special item = **manufacturer list price x CBC's customer-specific multiplier**.
The multiplier is a **per-vendor account attribute (a tier)**, not a per-item value.
**MAP is not cost.** Price changes arrive as dated memos with a protection window.

Phase 1 covers the **top-10 vendors only** — they are 90%+ of quotes.

## Hager — ~75% of volume
Account **HGR 17907**, discount sheet effective **03/02/2026**, Price Book **#18**.
Advantage Program: prepaid freight $1,500 (drop-ship $5,000); no minimum order charge;
crating $50.00; itemization/tagging $175.00.

| Product category | Discount | Multiplier |
|---|---|---|
| Locks | 50/42% | **0.290** |
| Door controls | 50/40% | **0.300** |
| Exit devices | 50/40% | **0.300** |
| L, DC and E accessories | 50/40% | 0.300 |
| Electrified products (excl. HS4) | 50/18% | **0.410** |
| Auto operators | 50/20% | 0.400 |
| Architectural hinges | 50/58% | **0.210** |
| Residential hinges | 50/25% | 0.375 |

Worked example from the requirements: a 3500-series storeroom lock lists **$256.31**;
at the 50-and-42 discount (0.290) cost is about **$74**.

## Other active vendors
| Vendor | Tier / multiplier | Note |
|---|---|---|
| ASI | **0.375** | Price list eff. 1-12-26 |
| National Guard Products | **0.45** | Price list eff. 6-8-2026 |
| Rockwood — accessories | **0.55** | Architectural and Lites/Louvers books also on file |
| Bradley | **0.53** | 2026 price book (WAD) |
| World Dryer | Level 3 = **0.339** | Vendor sheet pre-computes net |
| PEMKO / Markar | buying program acct **4244636** | 2026 price book on file |
| Bobrick / Gamco | HP 2017 program net sheets | net pricing, not list x multiplier |
| NUDO / Midwest-East Coast | FRP + vinyl moldings sheets eff. 5-11-26 | see [[manual_cutoff]] |

## Distributor-bought lines — MANUAL price entry (NR-2)
Not bought direct, so no multiplier applies. **Always require manual entry** with a
"price may be out of date — refresh" prompt:
- **Allegion** (Von Duprin, LCN, Schlage, Ives) via **Banner Solutions** or **SecLock**
- Restroom accessories via **J2**
- Laminate via **Pionite** / **Wilsonart**

## Adders not shown cleanly in the price book (NR-4)
Electrification, non-removable-pin (NRP) hinges, premium / lead-time finishes.
These are added **on top of** the base price — see
reference-library/adders/manual_adders.json

See [[cost_sourcing_rules]], [[margin_sheet]].
