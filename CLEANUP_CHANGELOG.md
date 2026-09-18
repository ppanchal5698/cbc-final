# Cleanup changelog

Every file created, updated, merged or archived by the agent-config audit, with
a one-line reason. Newest batch last.

Nothing is deleted. Anything removed from its original location is copied to
`_archive/<original-relative-path>` first, with a timestamp header.

---

## Batch 1 — audit deliverables (2026-09-18T12:30:58Z)

| File | Action | Reason |
|---|---|---|
| `WORKSPACE_INVENTORY.md` | created | Phase 1: every agent-steering file, with size, date and what it actually contains. |
| `AUDIT_FINDINGS.md` | created | Phase 2: contradictions, redundancies, orphans, scope violations, stale content. |
| `CLASSIFICATION.md` | created | Phase 3: every instruction fragment placed in one bucket. |
| `CLEANUP_CHANGELOG.md` | created | This file. |
| `_archive/` | created | Destination for anything removed in later batches. |

No existing file was read-modified or moved in this batch.

## Batch 2 — rules merged 9 → 5 (2026-09-18T12:33:14Z)

| File | Action | Reason |
|---|---|---|
| `.claude/rules/00-core-constraints.md` | created | Merge of `file-safety.md` + `human-in-the-loop.md` — the only two rules that apply to every task, both hook-enforced. |
| `.claude/rules/extraction.md` | created | Merge of `accuracy-trust.md` + `pdf-verify-before-present.md` — they already cross-referenced each other; the 0.75 floor is now stated once. |
| `.claude/rules/pricing.md` | created | Merge of `p21-read-only.md` + `margin-governance.md`. Notes that margin bands are also served live by the reference MCP server. |
| `.claude/rules/takeoff.md` | created | Straight move of `scope-boundaries.md`; content unchanged, retitled for the phase it applies to. |
| `.claude/rules/README.md` | created | Which rule applies when, and how to decide where a new one belongs. |
| `.claude/rules/auditability.md` | unchanged | Already single-topic and correctly scoped. |
| `docs/data_stewardship.md` | created | Content of `data-stewardship.md`. It reports a project gap, it does not steer an agent — it was costing every session context for nothing. |
| `.claude/rules/{file-safety,human-in-the-loop,margin-governance,p21-read-only,accuracy-trust,pdf-verify-before-present,scope-boundaries,data-stewardship}.md` | archived, then removed | Superseded by the five files above. Copies in `_archive/.claude/rules/` with timestamp headers. 313 lines preserved. |

**No constraint changed.** Every threshold, forbidden operation, hook path, exit
code, literal halt message and named owner survives. The `@.claude/memory/...`
inlines became plain paths, so those two memory files are no longer dragged into
every session.

## Batch 2b — correction: guides moved out of the auto-loaded directory (2026-09-18T12:34:37Z)

Merging 9 rules into 5 did **not** reduce the always-loaded payload — it went
*up*, 318 → 389 lines. Everything in `.claude/rules/` is injected regardless of
how it is grouped, so grouping alone saves nothing. The saving only comes from
moving phase-specific content out of that directory.

| File | Action | Reason |
|---|---|---|
| `.claude/guides/extraction.md` | moved from `rules/` | Applies to take-off and extraction only. |
| `.claude/guides/pricing.md` | moved from `rules/` | Applies to cost sourcing and margin only. |
| `.claude/guides/takeoff.md` | moved from `rules/` | Applies to scoping only. |
| `.claude/rules/README.md` | rewritten | Routes to the guides; trimmed, since it is itself always loaded. |

**Always-loaded payload: 318 → 163 lines (−49%).** `00-core-constraints.md` (88)
+ `auditability.md` (37) + `README.md` (38).

Trade-off worth naming: the three guides were previously guaranteed to be in
context. They are now one `Read` away, routed from the always-loaded README.
Each is still mechanically backed — `post_extraction_validate.py` and
`check_extraction` for extraction, the margin-band check for pricing — so the
text is guidance, not the only thing standing between a mistake and the quote.

## Batch 3 — core files and cross-references (2026-09-18T12:40:33Z)

| File | Action | Reason |
|---|---|---|
| `CLAUDE.md` | rewritten | Trimmed to a map. The six hand-maintained inventory lists (skills, rules, memory, commands, agents, MCP servers) are gone — they duplicated a directory listing and were the most rot-prone thing in the file. Original archived. |
| `AGENTS.md` | replaced with `@CLAUDE.md` | It was byte-identical to `CLAUDE.md`, so it was 51 lines of pure duplication loaded every session. `apps/web/CLAUDE.md` already used this pattern. Original archived. |
| `.claude/mcp/README.md` | created | What each of the 8 servers is for, in plain language, and which one writes. No such doc existed. |
| 7 memory / skill files | updated | Prose pointers to rules that moved now name the guide instead. |
| 10 agent / skill files | updated | Path references to the 8 moved rule files repointed. |

**Always-loaded payload: 485 → 231 lines (−52%).**

| | Before | After |
|---|---:|---:|
| `CLAUDE.md` | 51 | 67 |
| `AGENTS.md` | 51 | 1 |
| `.claude/rules/` | 318 | 163 |
| memory pulled in by `@`-inline | 65 | 0 |
| **Total** | **485** | **231** |

`CLAUDE.md` grew by 16 lines because it now routes explicitly instead of listing
file names. That is the trade: a map that stays true against six lists that
silently rot.

### ⚠ Requires a human — one broken test

Moving `scope-boundaries.md` → `.claude/guides/takeoff.md` broke
`apps/backend/tests/modules/extraction/test_scope_rules.py::test_the_rules_match_the_written_rule_file`,
which reads the old path directly at line 156. The file content is intact and
every asserted phrase is still present — only the path is stale.

This audit may not edit non-markdown source, so it is flagged rather than fixed.
The change is one line:

```python
-    rule_text = (ROOT / ".claude" / "rules" / "scope-boundaries.md").read_text(
+    rule_text = (ROOT / ".claude" / "guides" / "takeoff.md").read_text(
```

Verified: `pytest tests/modules/extraction/test_scope_rules.py` is currently
1 failed, 29 passed. Nothing else in the suite reads a path that moved.

## Batch 5 — verification and close (2026-09-18T12:43:12Z)

| File | Action | Reason |
|---|---|---|
| `apps/backend/tests/modules/extraction/test_scope_rules.py` | updated **(with explicit approval)** | Read `.claude/rules/scope-boundaries.md` directly; repointed to `.claude/guides/takeoff.md`. Docstring and failure message updated to match. Non-markdown, so it was flagged first and only changed once you approved. |
| `.claude/rules/00-core-constraints.md` | fixed link | Linked `pricing.md` as a sibling; it now lives in `../guides/`. |
| `ARCHITECTURE.md` | fixed link | Pointed at `.claude/rules/scope-boundaries.md`. |
| `CLEANUP_SUMMARY.md` | created | Before/after, what moved, how to maintain it, and what was left open. |

Verification: no `@`-inline in any always-loaded file · every `.md` link
resolves · 8 of 8 MCP servers documented · 139 passed / 13 skipped across every
test that reads an agent-config file · always-loaded payload 485 → 226 lines.

**Audit complete.**
