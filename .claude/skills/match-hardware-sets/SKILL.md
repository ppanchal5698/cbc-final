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

What CBC already decided, then the product catalog, then the PDF. Run in order
and stop at the first tier that produces a match.

| Tier | Test | Confidence |
|---|---|---|
| 0 | An estimator already confirmed this spec: `mcp__catalog__recall_match(specified)` returns `exact: true` | 0.97 |
| 1 | Exact part in the product catalog (`mcp__catalog__lookup_catalog_item` / `mcp__catalog__search_catalog_items`), all attributes agree | 0.95 - 1.00 |
| 2 | Exact part in the product catalog, one soft attribute differs (finish, size) | 0.75 - 0.94 |
| 3 | Series / prefix match in the product catalog (e.g. `3500` for `3547`), function inferable | 0.55 - 0.74 |
| 4 | Fuzzy description match off the PDF - `mcp__catalog-docs__search_blocks`, or `mcp__catalog__find_pages` when the parse is not ready | 0.40 - 0.54 |
| 5 | No usable match, or a MANUAL cut-off trigger | 0.00 |

A Tier 0 match cites who confirmed it and when in `substitution_note`. A near
recall (`exact: false`) is a candidate, not an answer: score it on its own tier.
Fire rating, handing and finish still veto a recalled match.

Pass the part **as the schedule writes it**; the catalog tools normalise it and
report what they matched on in `matched_on`. A catalog miss is an answer, not a
reason to search harder - the catalog holds no Allegion and no Zero.

`find_pages` and `search_blocks` route to vendor PDF pages — they do not return
prices.

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

Allegion (Von Duprin, LCN, Schlage, Ives) is bought through Banner Solutions or
SecLock and the product catalog holds none of it. Carry the specified part across
for trace, then set `cost_source: "DISTRIBUTOR_MANUAL"`, `confidence: 0.0`,
`cost: null` and a reason - never a catalog tier or a cost, even when Ives pages
appear in the Hager price book.

## MANUAL cut-off

Emit `confidence: 0.0`, `cost_source: "MANUAL"` and a plain-language reason when
the item is a custom size, an unusual prep, an option not sold in years, or
simply absent from every price book. A distributor-bought line is
`DISTRIBUTOR_MANUAL` instead (above). Do not substitute the nearest stock item to
avoid an empty cell.

## Reference data

- @.claude/memory/vendor_tiers.md
- @.claude/memory/fire_rating_rules.md
- @.claude/memory/finish_nomenclature.md
- @.claude/memory/manual_cutoff.md
- `references/hw_set_library.md`

## Output schema

Write to `projects/{project}/extracted/hardware_sets.json`, with the sets under
`groups`, each keyed by `hardware_set`. Add the match fields to the seeded items.

```json
{
  "project": "dutch_bros_macarthur_2026",
  "matched_at": "2026-08-26T12:00:00Z",
  "groups": [
    {
      "hardware_set": "GROUP 1",
      "openings": ["01"],
      "source_page": 14,
      "items": [
        {
          "category": "hinge",
          "specified": { "manufacturer": "IVES", "part_number": "700", "size": "83\"", "finish": "630" },
          "matched": {
            "manufacturer": "IVES",
            "part_number": "700",
            "source": "as specified - the product catalog holds no Allegion"
          },
          "confidence": 0.0,
          "match_tier": 5,
          "cost_source": "DISTRIBUTOR_MANUAL",
          "cost": null,
          "cost_source_detail": "Allegion (Ives) - distributor quote via Banner Solutions / SecLock; price may be out of date - refresh",
          "substitution_note": null,
          "flags": ["allegion_distributor_manual"]
        }
      ]
    }
  ],
  "unmatched": [],
  "review_required": []
}
```
