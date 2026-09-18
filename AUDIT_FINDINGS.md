# Audit findings — agent configuration surface

Phase 2 of the config audit. Analysis only; nothing was changed to produce this.
Source data: [`WORKSPACE_INVENTORY.md`](WORKSPACE_INVENTORY.md).

**Headline:** nothing here is broken. Every list in `CLAUDE.md` matches disk and
there are no dead references. The cost is context, not correctness — 318 lines
of rules load on every session regardless of the task, and the same constants
are restated in up to six places each.

---

## 1. Contradictions

### 1.1 `CLAUDE.md` forbids `@`-inlining; two rules do it anyway

`CLAUDE.md:14` reads:

> Rules under `.claude/rules/` load automatically. Do not `@`-inline them (or
> memory/skills) into this file — cite paths in plain text.

Two rules inline memory files regardless:

- `.claude/rules/accuracy-trust.md:16` → `@.claude/memory/manual_cutoff.md`
- `.claude/rules/margin-governance.md:11` → `@.claude/memory/margin_sheet.md`

Because rules load unconditionally, those two memory files are pulled into
**every** session too. This is the exact cost the instruction exists to prevent;
the instruction just scopes itself to `CLAUDE.md` and the rules sidestep it.

**Severity: real.** Silently inflates every session.

### 1.2 Two different staleness windows — deliberate, do not "fix"

- `.claude/rules/data-stewardship.md` — price sheets go stale at **~24 months**
- `.claude/rules/p21-read-only.md` — P21 cost unreliable past **6 months**,
  discard past **3 years**

`data-stewardship.md` already anticipates the confusion:

> The P21 freshness rule … is a different window from the ~24-month price-sheet
> one above, and moving one must not move the other.

**Severity: none.** Recorded so a future reader does not helpfully unify them.

---

## 2. Redundancies

Constants restated as prose in several files. There is no mechanism keeping them
in step, so changing one leaves the others quietly wrong.

| Fact | Files |
|---|---|
| `0.75` confidence floor | `rules/accuracy-trust.md`, `rules/pdf-verify-before-present.md`, `skills/match-hardware-sets/SKILL.md`, `skills/validate-extraction/references/validation_rules.md` |
| `US26D` / `626` finish notation | `memory/finish_nomenclature.md`, `skills/extract-door-schedule/SKILL.md`, `skills/extract-door-schedule/references/schedule_anatomy.md`, `skills/match-hardware-sets/SKILL.md`, `skills/validate-extraction/SKILL.md`, `skills/validate-extraction/references/validation_rules.md` |
| `0.29` Hager multiplier | `memory/vendor_tiers.md`, `skills/apply-margin/references/margin_bands.md`, `skills/price-line-item/references/cost_paths.md`, `skills/scan-product-catalog/SKILL.md` |

Whole-file duplication:

- **`CLAUDE.md` and `AGENTS.md` are byte-identical** (51 lines each, verified
  with `cmp`). `apps/web/` already solves this correctly: `apps/web/CLAUDE.md` is
  the single line `@AGENTS.md`.

---

## 3. Orphans and dead references

**None found.** Every inventory in `CLAUDE.md` matches disk exactly:

| Declared in `CLAUDE.md` | Declared | On disk |
|---|---:|---:|
| Skills | 10 | 10 |
| Rules | 9 | 9 |
| Memory files | 13 | 13 |
| Commands | 4 | 4 |
| Agents | 11 | 11 |
| MCP servers | 8 | 8 |

No skill is unreferenced; no rule points at something that has moved.

The lists are nonetheless the most rot-prone thing in the file — they are
maintained by hand and duplicate a directory listing.

---

## 4. Scope violations

### 4.1 Seven of nine rules are phase-specific but always loaded

| Rule | Actually applies during |
|---|---|
| `file-safety.md` | **always** — hook-enforced write/delete guard |
| `human-in-the-loop.md` | **always** — hook-enforced send block (NFR-1) |
| `auditability.md` | extraction and pricing (provenance on every record) |
| `accuracy-trust.md` | extraction / matching |
| `pdf-verify-before-present.md` | extraction |
| `scope-boundaries.md` | take-off |
| `margin-governance.md` | pricing |
| `p21-read-only.md` | pricing |
| `data-stewardship.md` | never (see 4.2) |

Only the first two are genuinely universal, and both are backed by hooks that
enforce them whether or not the text is in context.

### 4.2 `data-stewardship.md` is a status report, not a rule

41 always-loaded lines whose substance is "NFR-10 is OPEN, no owner or cadence
has been assigned", plus a table of `UNASSIGNED` / `UNDEFINED` cells. It states
a project gap. It does not steer agent behaviour and contains no instruction an
agent can follow.

Belongs in `docs/` alongside the other open-item tracking.

---

## 5. Stale content

### 5.1 Markdown shadows live, editable data

Five memory files restate values the `reference` MCP server serves
authoritatively — and which the app now has a settings UI for editing
(`/settings` → margin bands, tax rates, finishes, frame depths, vendor tiers,
backed by `PATCH /api/reference/*`).

| Memory file | Authoritative source |
|---|---|
| `memory/margin_sheet.md` | `mcp__reference__get_margin_bands` · `PATCH /api/reference/margins` |
| `memory/finish_nomenclature.md` | `mcp__reference__get_finish_crosswalk` · `PATCH /api/reference/finishes` |
| `memory/frame_depths.md` | `mcp__reference__get_frame_depth` · `PATCH /api/reference/frame-depths` |
| `memory/vendor_tiers.md` | `mcp__reference__get_vendor_tier` · `PATCH /api/reference/vendor-tiers` |
| `memory/sales_tax_rules.md` | `mcp__reference__get_tax_rates` · `PATCH /api/reference/tax` |

An estimator changing a margin band in the UI does not update the markdown. An
agent reading the markdown then gets the old number with nothing to indicate it
is stale. `margin_sheet.md` is the sharpest case: it is `@`-inlined by
`margin-governance.md`, so the shadowed copy is in **every** session.

**Severity: real, and a correctness risk rather than a tidiness one.** Routed to
§6 rather than fixed, because which copy should win is a judgement about
pricing, not about file structure.

---

## 6. Unclear — needs human review

Not guessed at, per the audit's own rule.

1. **The five files in §5.1 — archive, or keep as an offline fallback?**
   Archiving makes the MCP server the single source of truth and removes the
   divergence risk. Keeping them means an agent can still price when the server
   is unreachable, at the cost of two copies that will drift. This is a call
   about what is authoritative for money, and it is yours.

2. **`memory/process_flow.md`** — 6 lines. Cannot tell whether it is an
   abandoned stub or a deliberate pointer to `docs/cbc_process_flow.md`.

3. **`memory/estimator_profiles.md`** — names individuals and their habits.
   Cannot tell whether an agent is meant to change behaviour based on who is
   running it, or whether this is background reference material.

## 7. Flagged, not edited — outside this audit's remit

- **`.claude/hooks/*.py`** — Python, and three files
  (`post_tool_use.py`, `pre_delete_guard.py`, `pre_tool_use.py`) have
  uncommitted local modifications. Separately, `pre_tool_use.py` currently logs
  `WARN: tool_session guard skipped: No module named 'cbc'` on every tool call —
  its session guard is inert because the backend package is not on `PYTHONPATH`.
  The `git-push` block still fires, so nothing is being let through.
- **`apps/web/AGENTS.md`** — machine-generated by `next dev`, which rewrites it.
  It says so itself. Must not be hand-edited.
- **`.mcp.json`**, **`.claude/settings.json`** — config, not markdown.
