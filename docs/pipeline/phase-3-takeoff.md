# Phase 3 — Drawing take-off

Establishes the door and opening schedule. This is the phase the rest of the
quote is built on, and it is the one that works differently from every other
phase.

| | |
|---|---|
| **Agent** | `takeoff-engineer` — **sonnet** |
| **Job type** | part of `extract_bid_set`; one leg of the take-off wave |
| **Script** | `bash workflows/phase3_takeoff.sh <project>` |
| **Command** | `/takeoff` |
| **Skill** | `extract-door-schedule` |
| **Writes** | field patches to `extracted/line_items.json` — **schema-gated, blocking, patch-only** |

## The agent does not author the schedule

Before any token is spent, `extraction/infrastructure/pretakeoff.py` parses the
schedule deterministically in code and writes
`extracted/door_schedule.extracted.json`, which seeds
`extracted/line_items.json`.

`takeoff-engineer`'s job is to **check that seed against the sheets** and
correct it field by field through `mcp__artifact-storage__propose_patch`, each
patch carrying `{source_page, excerpt}` evidence. It is the only agent with
`propose_patch`, and it runs on Sonnet because deciding whether a schedule cell
really says what the parser thinks it says is judgment.

A whole-file `save_artifact` over an already-seeded `line_items.json` is
**blocked** by the `checkpoint-propose-patch` hook rule. A patch that fails
costs that one field and leaves a review flag; if nothing applies, the file is
left alone rather than rewritten byte-identically.

`parse_schedule.py` (in the skill) is run only when the seed produced nothing.

## What a patch must establish

The FR-2 checklist per opening: mark, size, handing, finish, fire rating, frame
type, wall type, hardware group. Plus the minute details that a deterministic
pass leaves in `raw_row` — glass, materials, frame-type digits, detail and note
codes. **Every non-empty schedule cell maps to an allowlisted field or into
`notes`.** Dropping `TEMP.` glass or an `HM`/`HMD` material because the parser
did not map it is a defect.

| Cell | Goes to |
|---|---|
| mark, size, type, materials, glass, HW group, keying | allowlisted `Opening` fields |
| thickness, detail refs, note numbers | `notes` — never a new key |
| door / frame type schedule callouts | cross-read those pages; fill rating and construction when stated |
| floor-plan swing | `handing` — a required search when the schedule has no HAND column |

Notation is read from `.claude/memory/`: `door_notation` (4-digit sizes),
`handing_codes` (LH/RH/LHR/RHR), `finish_nomenclature` (US26D ↔ 626),
`fire_rating_rules`, `frame_depths`.

## Verify before flagging

The gate applies whenever a required field is null and you are about to emit
`*_missing`, whenever confidence would fall below 0.75, whenever two sources
disagree, and whenever a schedule cell exists but was not mapped.

1. **Name the page** from `source_page`, the sheetmap, or `search_blocks` —
   never invent a page number.
2. **Read that page.** If it appears in `extracted/_visual_pages.json`, start
   with the pre-rendered image; otherwise `get_page_blocks` / `extract_tables` /
   `extract_text`. Crop with `get_page_image(region=bbox)` when the text layer
   is ambiguous.
3. **Record what you checked** in `evidence_note` — tool, page, and a short
   excerpt or "not found after search of pages …".
4. **Only then** fill the value, leave it null and flag, or raise an RFI.

Writing `*_missing` from the parser summary without opening the sheet is a
defect, not a shortcut.

## Tools

`mcp__bid-docs__*` to locate · `mcp__pdf-tools__*` to read (including
`parse_door_openings` and `get_page_image` for crops) ·
`mcp__artifact-storage__propose_patch` to correct ·
`mcp__reference__get_frame_depth` for wall-type-to-depth.

## Concurrency

Phases 3, 3b and 3c run at the same time. When the worker runs them as a
**wave** they share one sandbox with disjoint artifacts and each leg is told
what its siblings own. When the orchestrator delegates instead, the session
guard holds a lock on `extracted/line_items.json` so the orchestrator cannot
read it while this agent is still writing. See
[`../backend/worker.md`](../backend/worker.md#waves).

## Output

`extracted/line_items.json`, validated against `extracted_line_items.schema.json`.
A failure **blocks**. Every opening carries `source_file`, `source_page`,
`bbox`, `page_size` and `extracted_at`.

## Handoff

[Phase 4](phase-4-pricing.md) matches these openings to catalog entries. Note
that `product-matcher` has **no PDF tools at all** — if it needed the drawing
again, this phase was wrong.
