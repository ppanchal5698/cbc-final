---
name: extract-door-schedule
description: >
  Extracts the door / opening schedule from an architectural PDF. Captures door
  number, size (4-digit notation or explicit feet-inches), handing (LH/RH/LHR/RHR),
  finish (US26D/626 dual nomenclature), fire rating (20/45/60/90-minute), frame
  type, wall type and hardware-group callouts. Use in Phase 3 (drawing take-off)
  of a CBC bid. Phase 2 records hardware-group page numbers only — spec-scope-analyst
  owns that; takeoff-engineer owns item-level extraction here.
---

# Extract Door Schedule

## Why this is not just "read the table"

Architectural bid sets are CAD exports. A single sheet in the Dutch Bros fixture
carries over 13,000 vector line segments, and `pdfplumber.find_tables()` returns
35 candidates of which roughly one is the schedule. **Do not trust ruling-based
table detection.** Rows are recovered by clustering positioned words instead.

## Steps

1. **Locate the schedule.** Use `mcp__pdf-tools__search_pdf` for `DOOR SCHEDULE`,
   `DOOR TYPE SCHEDULE`, `DOOR FRAME TYPE SCHEDULE`, `HARDWARE GROUPS`, and
   `WINDOW SCHEDULE`. Record every hit's `source_page`. The schedule usually sits
   on a details/schedules sheet (A2.x), not on the spec pages that merely
   reference it.
2. **Pull the rows.** Run `.claude/skills/extract-door-schedule/scripts/parse_schedule.py <pdf> --page <n>`, or call
   `mcp__pdf-tools__extract_tables` with that page. Both cluster words by
   y-position into rows.
3. **Parse each opening.** Map the row cells onto the fields below. The column
   order varies by architect - identify columns from the header row, never by
   fixed index.
4. **Resolve sizes.** 4-digit notation: first two digits are width in
   feet-inches, last two are height (`3070` = 3'-0" x 7'-0"). Many sets instead
   write `3' - 0"` and `7' - 0"` in separate columns - handle both and normalise.
5. **Capture the hardware group** (`GROUP 1`, `HW-1`, `HDW-01`) and, separately,
   parse the **HARDWARE GROUPS** block into its component items.
6. **Capture bid alternate designation** when the schedule or notes mark an
   opening as Alternate 1 / ALT-1 / similar (FR-2). Write it as `alternate` on
   the opening (sync maps it to `alternateGroup`). Leave null for base-bid rows.
7. **Normalize finishes** via the dual nomenclature crosswalk
   (`mcp__reference__get_finish_crosswalk` / NR-3). Prefer recording
   the US code when known (`US26D`); import will store the canonical pair
   `US26D (626)`. Never treat US19 as US26D. Unknown finishes stay as written
   and get flagged — do not invent a mapping.
8. **Flag, do not fill.** Any missing rating, handing, finish or size is recorded
   as `null` with a review flag. Never infer an attribute from a neighbouring row.

## Field definitions

See `references/schedule_anatomy.md` for the full anatomy, including the
hardware-set composition and the two size notations.

## Reference data

- @.claude/memory/door_notation.md
- @.claude/memory/handing_codes.md
- @.claude/memory/finish_nomenclature.md
- @.claude/memory/fire_rating_rules.md
- @.claude/memory/frame_depths.md

## Output schema

Write to `projects/{project}/extracted/door_schedule.json`:

```json
{
  "project": "dutch_bros_macarthur_2026",
  "source_file": "uploads/raw/1_Architectural.pdf",
  "extracted_at": "2026-08-26T12:00:00Z",
  "openings": [
    {
      "door_number": "01",
      "size": "3670",
      "width": "3'-6\"",
      "height": "7'-0\"",
      "handing": null,
      "finish": null,
      "fire_rating": null,
      "door_type": "A",
      "frame_type": "1",
      "door_material": "HM",
      "frame_material": "HMD",
      "glass": "TEMP.",
      "wall_type": null,
      "frame_depth": null,
      "hardware_set": "GROUP 1",
      "alternate": null,
      "notes": "A,B,C,D,E,F",
      "source_page": 14,
      "bbox": [640.2, 609.8, 998.4, 619.1],
      "page_size": { "width": 2592.0, "height": 1728.0 },
      "row_bbox": [640.2, 609.8, 998.4, 619.1],
      "cell_boxes": [[640.2, 609.8, 690.0, 619.1]],
      "confidence": 0.9,
      "flags": ["fire_rating_missing", "handing_missing", "finish_missing"]
    }
  ],
  "hardware_groups": [
    {
      "group": "GROUP 1",
      "source_page": 14,
      "items": [
        { "category": "hinge", "manufacturer": "IVES", "part_number": "700", "size": "83\"", "finish": "630" }
      ]
    }
  ],
  "unparsed_regions": [],
  "confidence": 0.9
}
```

## Script

```bash
python .claude/skills/extract-door-schedule/scripts/parse_schedule.py <pdf> --find
python .claude/skills/extract-door-schedule/scripts/parse_schedule.py <pdf> --page 14 --openings --json
```

`--find` locates candidate schedule pages. `--page N --openings` parses opening
rows with bbox and page_size. `--json` emits machine-readable output; with
`--openings` the envelope is `{"openings": [...]}` ready for door_schedule.json.
