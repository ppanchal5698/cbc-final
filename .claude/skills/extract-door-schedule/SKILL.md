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

## Deterministic-first (mandatory)

1. Read `extracted/door_schedule.json` if it exists (worker pretakeoff /
   `parse_schedule.py` often already wrote it).
2. If missing → **run the script or MCP** on sheetmap `door_schedule` pages.
   Do **not** freehand-author openings:

       python .claude/skills/extract-door-schedule/scripts/parse_schedule.py <pdf> \
         --page <n> --openings --json

   Prefer `mcp__pdf-tools__parse_door_openings(file_path, page_number)` when
   available — it applies rotation-safe clustering and FR-2 field mapping.
3. **FR-2 field checklist** (estimator order) — fill nulls from evidence only:
   - door number / mark, size (W×H), handing, finish, fire rating, hardware
     group **or** matrix hardware, alternate when marked
   - **door_type / frame_type / materials / glass** — copy every non-empty cell;
     put thickness, detail refs, note letters into `notes`
   - **Handing:** schedule column → else floor-plan swing → else flag
     (`handing_missing`). Never default LH.
   - **Fire rating:** schedule → door/frame type schedule → Div 08 notes → else
     flag (`fire_rating_missing`). Never invent. Accept explicit `NR`.
   - **Finish:** row, HW group, or sheet note ("ALL HARDWARE SHALL BE US32D").
   - **Storefront / AL+AL:** flag `out_of_scope_storefront`; do not quote as CBC
     HM/WD lines (Matrix 2.3).
4. **PDF verify before present (mandatory).** Before emitting any `*_missing`
   flag, filling an unsure value, or saving an opening that drops cells from
   `raw_row`, open the **specific** PDF page(s):
   `search_blocks` / `get_page_blocks` or `extract_tables` / `extract_text`,
   crop with `get_page_image(region=bbox)` when ambiguous. Cite page + excerpt
   (or "searched pages … — not found") in `evidence_note`. See
   @.claude/rules/pdf-verify-before-present.md. Parser null ≠ sheet silent.
5. Persist with `mcp__artifact-storage__save_artifact` only — never Write/Edit.
6. On schema error: repair named fields (≤2 retries). Do not bypass validation.

## Why this is not just "read the table"

Architectural bid sets are CAD exports. A single sheet in the Dutch Bros fixture
carries over 13,000 vector line segments, and `pdfplumber.find_tables()` returns
35 candidates of which roughly one is the schedule. **Do not trust ruling-based
table detection.** Rows are recovered by clustering positioned words instead.

## Steps

1. **Locate the schedule.** Prefer `_sheetmap.json` roles `door_schedule` /
   `hardware`. Else `search_pdf` / `search_blocks` for `DOOR SCHEDULE`,
   `DOOR TYPE SCHEDULE`, `HARDWARE GROUPS`. Record every hit's `source_page`.
2. **Pull the rows.** Prefer
   `mcp__pdf-tools__parse_door_openings` or
   `.claude/skills/extract-door-schedule/scripts/parse_schedule.py <pdf> --page <n> --openings --json`.
   Fallback: `mcp__pdf-tools__extract_tables` on that page (also rotation-safe).
3. **Map cells onto the allowlist below.** Column order varies — identify from
   the header. Unknown columns (e.g. Thickness) go into `notes`, never as new keys.
4. **Resolve sizes.** 4-digit: `3070` = 3'-0" x 7'-0". Or explicit feet-inches.
5. **Hardware:** `GROUP n` / `HW-n` **or** matrix X columns → expand legend into
   `hardware` (flag `hardware_matrix_unexpanded` until expanded).
6. **Alternate** (FR-2) when marked; else null.
7. **Finishes** via dual nomenclature; never treat US19 as US26D.
8. **Handing / fire rating** — follow the estimator search order in
   `@.claude/memory/handing_codes.md` and `@.claude/memory/fire_rating_rules.md`.
9. **PDF verify gate.** For every null FR-2 field, read the candidate pages on
   the actual PDF before flagging. Write the search into `evidence_note`.
10. **Flag, do not fill** only after the search order **and** the PDF check are
    exhausted.

## Opening allowlist (closed world)

Emit **only** these properties on each opening (Pydantic `Opening`,
`extra="forbid"`). Anything else fails save_artifact.

**Identity / size:** `door_number`, `mark`, `description`, `raw_row`, `size`,
`width`, `height`, `size_notation`, `qty`

**Hardware / type:** `hardware_set`, `hw_set`, `hardware`, `door_type`, `type`,
`frame_type`, `door_material`, `frame_material`, `material`, `glass`, `glazing`,
`core`, `undercut`, `manufacturer`, `series`, `division`

**Attributes:** `handing`, `finish`, `fire_rating`, `wall_type`, `frame_depth`,
`alternate`, `alternate_group`, `location`, `room_name`, `status`, `notes`,
`comments`, `evidence_note`

**Provenance (required for viewer):** `source_file`, `source_page`, `sheet`,
`bbox`, `row_bbox`, `cell_boxes`, `page_size`, `row`, `confidence`, `flags`

**Dedupe / human:** `is_duplicate`, `duplicate_of`, `duplicate_reason`,
`confirmed_by`, `added_by_hand`

### `page_size` contract

```json
"page_size": { "width": 2448.0, "height": 1584.0 }
```

- **Must** be an object with numeric `width` and `height`.
- **Never** `[2448.0, 1584.0]` (MinerU array shape).
- Prefer parser output or `mcp__pdf-tools__get_page_size`.

### Unknown schedule columns

If the sheet has Thickness / THK / similar: append to `notes` as
`Thickness: 1 3/4"`. **Never** invent `thickness`, `thickness_in`, or other
non-allowlist keys. Do not add freeform envelopes like `extraction_notes`.

## Field definitions

See `references/schedule_anatomy.md`.

## Reference data

- @.claude/memory/door_notation.md
- @.claude/memory/handing_codes.md
- @.claude/memory/finish_nomenclature.md
- @.claude/memory/fire_rating_rules.md
- @.claude/memory/frame_depths.md

## Output schema

Save via **`mcp__artifact-storage__save_artifact`** to
`projects/{project}/extracted/door_schedule.json`:

```json
{
  "source_file": "uploads/raw/1_Architectural.pdf",
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
  "no_scope_reason": null
}
```

Top-level extras the wrapper ignores (`hardware_groups`, `confidence`) are
optional. Opening-level extras are **forbidden**.

## Script

```bash
python .claude/skills/extract-door-schedule/scripts/parse_schedule.py <pdf> --find
python .claude/skills/extract-door-schedule/scripts/parse_schedule.py <pdf> --page 19 --openings --json
```

`--find` locates candidate schedule pages. `--page N --openings` parses opening
rows with bbox and `page_size` object (rotation-safe). MCP equivalent:
`mcp__pdf-tools__parse_door_openings`.
