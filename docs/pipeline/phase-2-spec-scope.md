# Phase 2 — Spec scoping

Reads the specification PDFs to establish what CBC is quoting and what it is
not, before anyone counts a door.

| | |
|---|---|
| **Agent** | `spec-scope-analyst` (haiku) |
| **Job type** | part of `extract_bid_set` |
| **Script** | `bash workflows/phase2_spec_scope.sh <project>` |
| **Writes** | `extracted/scope_summary.json` — **schema-gated, blocking** |

## Inputs

`extracted/scope_metadata.json` and the parsed specification documents.

## What happens

1. **Find Division 08** — doors, frames and hardware — and **Division 10** —
   specialties, partitions, accessories, washroom equipment. Record which
   sections exist and on which pages.
2. **Extract fire ratings** stated in the spec (20 / 45 / 60 / 90 minute) so
   Phase 3 has something to check the schedule against.
3. **Record hardware-set callouts as page numbers only.** This is the boundary
   that matters: Phase 2 says "hardware groups are on pages 412–418".
   `takeoff-engineer` owns item-level extraction in Phase 3. Two agents
   extracting the same sets is how they come to disagree.
4. **Set the scope flags** the later phases branch on —
   `div10_in_scope`, FRP presence — so Phases 3b and 3c only run when there is
   something for them to do.
5. **Record out-of-scope items** under `out_of_scope_items`, each with its
   source page.

## Tools

`mcp__bid-docs__search_blocks` · `get_outline` · `get_page_blocks` — locate the
division sections.

`mcp__pdf-tools__extract_text` · `extract_tables` · `search_pdf` ·
`find_sheets` · `get_page_image` · `get_page_size` — read them.

`mcp__artifact-storage__save_artifact` — write the checkpoint. Note this agent
has **no `propose_patch`**: it authors the scope summary rather than correcting
a seeded one.

## Out of scope is a deliverable

An out-of-scope item is not silently dropped. It is recorded with its page,
never priced, and named in the review summary so the estimator can tell the
general contractor exactly what CBC is not covering. A GC who discovers the gap
after award is a worse outcome than a line that says "not quoted".

The list is in [`README.md`](README.md#scope). The storefront in the Dutch Bros
fixture (Kawneer 541T) is the worked example — it appears in the drawings, it is
read, and it is deliberately not quoted.

## Output

`extracted/scope_summary.json`, validated against `scope_summary.schema.json`.
A failure **blocks**.

## Handoff

The scope flags fan out to three concurrent take-offs:
[Phase 3](phase-3-takeoff.md) always, [Phase 3b](phase-3b-frp.md) where FRP is
specified, [Phase 3c](phase-3c-div10.md) when `div10_in_scope` is true.
