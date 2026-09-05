---
name: validate-extraction
description: >
  Validates extracted bid data before it is priced - checks required fields per
  opening, verifies fire ratings were not silently dropped on rated openings, and
  reports unparsed content. Use after any extraction step, and before Phase 4
  pricing begins.
---

# Validate Extraction

Extraction that quietly loses a field is worse than extraction that fails loudly.
This skill exists to make the losses visible.

## Required fields per opening

| Field | Required | If missing |
|---|---|---|
| `door_number` | yes | **hard error** - the opening cannot be grouped or quoted |
| `size` / `width` + `height` | yes | **hard error** - nothing can be priced without it |
| `source_page` | yes | **hard error** - the line would be unauditable (NFR-3) |
| `handing` | yes | flag `handing_missing` - try the floor plan before flagging |
| `finish` | yes | flag `finish_missing` - often lives in the hardware group |
| `fire_rating` | yes | flag `fire_rating_missing`, severity **high** |
| `hardware_set` | yes | flag `hardware_set_missing` |
| `frame_type` / `wall_type` | preferred | flag `frame_depth_underivable` |

## The fire-rating check

1. Did the spec or schedule indicate **any** rated openings in this bid?
2. If yes, does every opening carry either a rating or an explicit "not rated"?
3. Any opening that inherited `null` from a rated schedule is flagged at
   **severity high** - an unrated match on a rated opening is a defect.

Whether a missing rating should hard-stop the line is still an open question
(Matrix 7.3). Until CBC answers, **flag, do not stop**.

## Other checks

- **No silent inference.** If two adjacent openings share a value that only one of
  them stated, that is a bug, not a convenience.
- **Finish dual nomenclature (NR-3).** Prefer US codes from the schedule; import
  normalizes known finishes to `US26D (626)`. Flag `finish_ambiguous` when a
  numeric maps to more than one US code (e.g. 619 → US19 / US15). Never equate
  US19 with US26D.
- **Alternate designation (FR-2).** When the schedule marks an opening as an
  alternate, `alternate` must be set. Formal base+alternate reconciliation is
  still Pending (Matrix 4.1) — capture the tag only.
- **Source page on everything.** Every extracted record must name its page.
- **Confidence present** on every match, in 0.0-1.0.
- **Out-of-scope items recorded, not quoted** - the fixture's Kawneer 541T
  storefront belongs in `out_of_scope_items`, not in a line item.
- **Unparsed regions reported.** If a region of the schedule could not be read,
  say so with its page number.
- **Counts reconcile.** Openings extracted vs door numbers referenced on the floor
  plans - a mismatch usually means a whole schedule block was missed.

## Reference

- `references/validation_rules.md`

## Invocation

```bash
python scripts/validate_project.py --check-extraction dutch_bros_macarthur_2026
```

This also runs automatically as a PostToolUse hook whenever a file is written to
`projects/{project}/extracted/`. The hook warns; it never blocks.

## Output

Findings are merged into `projects/{project}/review/review_flags.json`:

```json
{
  "project": "dutch_bros_macarthur_2026",
  "validated_at": "2026-08-26T12:00:00Z",
  "errors": [],
  "flags": [
    {
      "opening": "01",
      "field": "fire_rating",
      "flag": "fire_rating_missing",
      "severity": "high",
      "source_page": 14,
      "note": "Door schedule carries no rating column. Matrix 7.3 is still open."
    }
  ],
  "summary": { "openings": 4, "errors": 0, "flags": 12 }
}
```
