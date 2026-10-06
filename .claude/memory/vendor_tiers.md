# Vendor Tiers & Multipliers

Cost for a non-special item = **manufacturer list price x CBC's customer-specific multiplier**.
The multiplier is a **per-vendor account attribute (a tier)**, not a per-item value.
**MAP is not cost.** Price changes arrive as dated memos with a protection window.

The multipliers are not written here. `mcp__catalog__get_multiplier(vendor, category)`
returns the one in force, with its effective date and price book (seed:
`data/reference-library/multipliers/vendor_tiers.json`, which purchasing maintains and
which is not in a run's workspace). This file used to carry a copy, and the copy drifted
from the sheet.

Phase 1 covers the **top-10 vendors only** — they are 90%+ of quotes.

## Hager — ~75% of volume
Account id lives with purchasing (see `data/reference-library/multipliers/vendor_tiers.json`).
Advantage Program: prepaid freight $1,500 (drop-ship $5,000); no minimum order charge;
crating $50.00; itemization/tagging $175.00.

Hager prices **by product category** - pass the category to `get_multiplier`:

| Product category | `category` |
|---|---|
| Locks | `locks` |
| Door controls | `door_controls` |
| Exit devices | `exit_devices` |
| L, DC and E accessories | `l_dc_e_accessories` |
| Electrified products (excl. HS4) | `electrified_products` |
| Auto operators | `auto_operators` |
| Architectural hinges | `architectural_hinges` |
| Residential hinges | `residential_hinges` |

The sheet has more; `get_multiplier` answers a category it does not recognise with
`available_categories` rather than a guess.

Worked example from the requirements: a 3500-series storeroom lock lists **$256.31**;
its cost is that list x the `locks` multiplier from `get_multiplier`.

## Other active vendors
| Vendor | Tier | Note |
|---|---|---|
| ASI | single tier, `get_multiplier` | Price list on file |
| National Guard Products | single tier, `get_multiplier` | Price list on file |
| Rockwood — accessories | single tier, `get_multiplier` | Architectural and Lites/Louvers books also on file |
| Bradley | single tier, `get_multiplier` | 2026 price book (WAD) |
| World Dryer | Level 3, `get_multiplier` | Vendor sheet pre-computes net |
| PEMKO / Markar | buying program account (see purchasing / `vendor_tiers.json`) | 2026 price book on file |
| Bobrick / Gamco | HP 2017 program net sheets | net pricing, not list x multiplier |
| NUDO / Midwest-East Coast | FRP + vinyl moldings sheets | see [manual_cutoff](manual_cutoff.md) |

## Distributor-bought lines — `DISTRIBUTOR_MANUAL` price entry (NR-2)
Not bought direct, so no multiplier applies. **Always require manual entry**
(`cost_source: DISTRIBUTOR_MANUAL`, cost null until priced) with a
"price may be out of date — refresh" prompt:
- **Allegion** (Von Duprin, LCN, Schlage, Ives) via **Banner Solutions** or **SecLock**
- Restroom accessories via **J2**
- Laminate via **Pionite** / **Wilsonart**

## Adders not shown cleanly in the price book (NR-4)
Electrification, non-removable-pin (NRP) hinges, premium / lead-time finishes.
These are added **on top of** the base price — from `mcp__reference__get_manual_adders`
(seed: `data/reference-library/adders/manual_adders.json`).

See [cost_sourcing_rules](cost_sourcing_rules.md), [margin_sheet](margin_sheet.md).
