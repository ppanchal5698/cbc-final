---
name: match-hardware-sets
description: >
  Matches each extracted opening and hardware-group item to the CBC reference
  library, respecting fire rating, handing and finish. Assigns a confidence score
  per match and flags anything below threshold for estimator review. Use after
  extract-door-schedule, in Phase 4 of a CBC bid.
---

# Match Hardware Sets

## Matching algorithm

Run in order. Stop at the first tier that produces a match.

| Tier | Test | Confidence |
|---|---|---|
| 1 | Exact part number in the reference library, all attributes agree | 0.95 - 1.00 |
| 2 | Exact part number, one soft attribute differs (finish, size) | 0.75 - 0.94 |
| 3 | Series match (e.g. `3500` for `3547`), function inferable | 0.55 - 0.74 |
| 4 | Fuzzy description match via `mcp__catalog__find_pages` (page index ranking) | 0.40 - 0.54 |
| 5 | No usable match, or a MANUAL cut-off trigger | 0.00 |

Catalog `find_pages` routes to vendor PDF pages — it does not return prices.

Read `extracted/_matchcache.json` when present. Reuse matches at confidence
≥ 0.75; rematch only uncached items. Do not reuse a cached entry below 0.75.

## Hard constraints - these are not soft attributes

1. **Fire rating.** An unrated match on a rated opening is a defect. If the
   opening carries a rating and the candidate is not rated, reject the match
   regardless of how good the rest looks.
2. **Handing.** Handed hardware (locks, closers, exit devices) must match LH /
   RH / LHR / RHR. If handing is unknown, do not pick a handed item - flag it.
3. **Finish.** `US19` and `US26D` are different satins. Do not substitute across
   them. Use `mcp__reference__get_finish_crosswalk` to reconcile the
   two nomenclatures before comparing.

## Manufacturer preference

1. Whatever the architect specified, by part number and series - that is the
   authority for what is required.
2. Hager, when the drawing specs a function with no named manufacturer.
3. A direct-equal from the top 2-3 brands when the specified line is unavailable -
   **always with a substitution note** naming what was specified and what is
   offered instead. The GC has to approve a direct equal.

Allegion (Von Duprin, LCN, Schlage, Ives) matches fine but has **no CBC price
book** - every Allegion line becomes `DISTRIBUTOR_MANUAL`.

## MANUAL cut-off

Emit `confidence: 0.0`, `cost_source: "MANUAL"` and a plain-language reason when
the item is a custom size, an unusual prep, an option not sold in years, a
distributor-bought line, or simply absent from every price book. Do not
substitute the nearest stock item to avoid an empty cell.

## Reference data

- @.claude/memory/vendor_tiers.md
- @.claude/memory/fire_rating_rules.md
- @.claude/memory/finish_nomenclature.md
- @.claude/memory/manual_cutoff.md
- `references/hw_set_library.md`

## Output schema

Write to `projects/{project}/extracted/hardware_sets.json`:

```json
{
  "project": "dutch_bros_macarthur_2026",
  "matched_at": "2026-08-26T12:00:00Z",
  "groups": [
    {
      "group": "GROUP 1",
      "openings": ["01"],
      "source_page": 14,
      "items": [
        {
          "category": "hinge",
          "specified": { "manufacturer": "IVES", "part_number": "700", "size": "83\"", "finish": "630" },
          "matched": {
            "vendor": "Allegion",
            "part_number": "700",
            "source": "referenceData/allegion_stock"
          },
          "confidence": 0.95,
          "match_tier": 1,
          "cost_source": "DISTRIBUTOR_MANUAL",
          "substitution_note": null,
          "flags": []
        }
      ]
    }
  ],
  "unmatched": [],
  "review_required": []
}
```
