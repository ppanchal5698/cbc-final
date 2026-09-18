---
name: extract-div10-takeoff
description: >
  Extracts Division 10 specialty take-off lines — toilet partitions, restroom
  accessories, washroom equipment, and hand dryers — with type, manufacturer,
  location, and counts. Use in Phase 3c when scope_summary.div10_in_scope is true.
---

# Division 10 Specialty Take-off

CBC extracts Div 10 quantities from bid PDFs for quoting later. This skill does
**not** price anything.

## In-scope product types

| `product_type` | Examples |
|---|---|
| `partition` | Toilet / urinal partitions and screens |
| `accessory` | Grab bars, mirrors, dispensers, paper holders |
| `hand_dryer` | Hand dryers (World Dryer / Excel XLERATOR preferred) |
| `washroom_equipment` | Other washroom fixtures in CBC Div 10 scope |
| `other` | Only when clearly Div 10 and none of the above fit |

Out of scope (do not quote): Scranton partitions, American Dryer (note only),
corner guards, signage, lockers — see .claude/rules/scope-boundaries.md.

## Steps

1. Confirm `div10_in_scope` in `extracted/scope_summary.json`.
2. Prefer sheetmap roles `div10` + `finish`; else search the markers above.
3. Read Div 10 schedules, accessory schedules, and finish plans. Capture every
   countable line with `source_page` and evidence.
4. Write via `save_artifact` to `extracted/div10_takeoff.json`.

## Output schema

```json
{
  "div10_in_scope": true,
  "status": "extracted",
  "items": [
    {
      "product_type": "accessory",
      "manufacturer": "Bobrick",
      "location": "Restroom 101",
      "room": "101",
      "drawing_ref": "A-501",
      "qty": 4,
      "unit": "ea",
      "specified_model": "1040",
      "finish": "stainless",
      "notes": null,
      "alternate": null,
      "source_page": 22,
      "evidence_note": "Accessory schedule row — Restroom 101",
      "flags": [],
      "confidence": 0.85
    }
  ],
  "flags": [],
  "confidence": 0.85
}
```

**Shape rules (strict):**
- Use `items` (not `line_items`). Each row uses `qty` and `specified_model` (not `quantity` / `model`).
- Top-level and per-item `flags` must be **strings** only — e.g. `"grab_bars_not_on_schedule"`. Never objects like `{"type":"info","message":"..."}`.
- Put narrative warnings in a string flag or in `notes` / `evidence_note`.

If Div 10 is flagged in scope but no countable lines appear after PDF verify,
keep `items: []` and set `no_scope_reason` naming pages searched.
