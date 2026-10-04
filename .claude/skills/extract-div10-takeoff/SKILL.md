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
corner guards, signage, lockers — see .claude/guides/takeoff.md.

## Steps

1. Confirm `div10_in_scope` in `extracted/scope_summary.json`.
2. Prefer sheetmap roles `div10` + `finish`; else search the markers above.
3. Read Div 10 schedules, accessory schedules, and finish plans. Capture every
   countable line with `source_page` and evidence.
4. Write via `save_artifact` to `extracted/div10_takeoff.json`.

## Output schema

The contract is `Div10Takeoff` / `Div10Item` / `Div10Mention` in
`apps/backend/src/cbc/modules/extraction/api/claude_output.py`; `pretakeoff`
seeds the file in this shape before you start. An item allows exactly the keys
shown below plus `source_file` - any other item key is folded into `notes` or
rejected. `bbox`, `cell_boxes` and `page_size` are measured from the sheet after
you write; do not supply them.

```json
{
  "div10_in_scope": true,
  "status": "EXTRACTED",
  "source_file": "uploads/raw/1_Architectural.pdf",
  "pages_read": [22],
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
  "mentions": [
    {
      "product_type": "accessory",
      "source_page": 23,
      "excerpt": "CONTRACTOR MAKING FINAL HOOK-UPS",
      "why_not_an_item": "no manufacturer and model on this row"
    }
  ],
  "flags": ["div10_mentions_need_review"],
  "confidence": 0.85,
  "no_scope_reason": null
}
```

`mentions` are rows that name an accessory without a manufacturer and model.
They are not lines to price; resolve one into an `items` row only when the
sheets give you the manufacturer and model, otherwise leave it for the
estimator.

**Shape rules (strict):**
- Use `items` (not `line_items`). Each row uses `qty` and `specified_model` (not `quantity` / `model`).
- Top-level and per-item `flags` must be **strings** only — e.g. `"grab_bars_not_on_schedule"`. Never objects like `{"type":"info","message":"..."}`.
- Put narrative warnings in a string flag or in `notes` / `evidence_note`.

If Div 10 is flagged in scope but no countable lines appear after PDF verify,
keep `items: []` and set `no_scope_reason` naming pages searched.
