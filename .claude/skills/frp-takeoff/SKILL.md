---
name: frp-takeoff
description: >
  Performs the FRP wall-panel take-off - captures perimeter linear feet, inside
  and outside corner counts and wall height from the drawings, then converts to
  material quantities using the estimator's constants. Use in Phase 3b of a CBC
  bid, wherever FRP wall panels are specified.
---

# FRP Take-off

## The constants are PENDING - this changes how the skill behaves

CBC has not yet provided the geometry-to-quantity conversion constants (Open Item
5). Until they land, this skill **captures geometry and stops**. It does not
estimate panel counts.

That is not a limitation to work around. A guessed panel size or waste factor
produces a confidently wrong quote, which is worse than an empty cell an
estimator can fill.

## Steps

1. **Confirm FRP is in scope for this bid.** Search the drawings and specs for
   `FRP`, `FIBERGLASS REINFORCED`, `WALL PANEL`, `J-CHANNEL`, `COVE BASE`. Record
   every `source_page`. In the Dutch Bros fixture, FRP appears on pages 2, 4, 12,
   14, 16, 19, 24 with J-channel and cove-base details on page 14.
2. **Identify the FRP walls.** Usually restrooms, kitchen and prep areas. Read the
   room finish schedule and the wall tags.
3. **Capture geometry** from the floor plan and wall sections:
   - perimeter linear feet per room
   - inside corner count
   - outside corner count
   - wall height (FRP often stops at a wainscot height, not the ceiling)
   - door and window openings, listed individually with their sizes
4. **Convert to quantities** - only if the constants are present. Call
   `mcp__reference__get_frp_constants` first. If
   `status` is `PENDING`, skip this step entirely and emit nulls.
5. **Write the take-off** with every geometry value traced to its `source_page`.

## Conversion, once constants exist

```
wall_area_sqft   = perimeter_lf x wall_height_ft - deducted_openings_sqft
panel_count      = ceil(wall_area_sqft / panel_coverage_sqft x (1 + waste_pct))
inside_corner_lf = inside_corner_count x wall_height_ft
outside_corner_lf= outside_corner_count x wall_height_ft
trim_sticks      = ceil(trim_lf / trim_stick_length)
adhesive_units   = ceil(wall_area_sqft / adhesive_coverage_sqft_per_unit)
```

## Reference data

- `references/frp_constants.md`
- @.claude/memory/process_flow.md - Phase 3b

## Output schema

Write to `projects/{project}/extracted/frp_takeoff.json`:

```json
{
  "project": "dutch_bros_macarthur_2026",
  "frp_in_scope": true,
  "status": "PENDING_CONSTANTS",
  "constants_source": "referenceData/frp_constants",
  "areas": [
    {
      "room": "Restroom 1",
      "perimeter_lf": null,
      "wall_height_ft": null,
      "inside_corners": null,
      "outside_corners": null,
      "openings_deducted": [],
      "source_page": 14,
      "confidence": 0.0
    }
  ],
  "quantities": {
    "panels": null,
    "inside_corner_trim_lf": null,
    "outside_corner_trim_lf": null,
    "division_bar_lf": null,
    "cap_trim_lf": null,
    "cove_base_lf": null,
    "adhesive_units": null
  },
  "blocked_on": "Open Item 5 - FRP conversion constants not yet provided by CBC",
  "flags": ["frp_constants_pending"]
}
```

## Vendors

NUDO, Marlite, Midwest-East Coast FRP. Price sheets are in `pricebooks/`
(`nudo_frp_pricing.pdf`, `nudo_vinyl_moldings_pricing.pdf`, both effective
2026-05-11).
