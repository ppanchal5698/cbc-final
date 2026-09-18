# Cleanup summary — agent configuration surface

Completed 2026-09-18. Full log: [`CLEANUP_CHANGELOG.md`](CLEANUP_CHANGELOG.md).
Reasoning: [`AUDIT_FINDINGS.md`](AUDIT_FINDINGS.md).

## The headline

**Every session was carrying 485 lines of instructions. It now carries 226 — a
53% cut — and no constraint changed.**

The saving came from one realisation: everything in `.claude/rules/` is injected
whether or not the task touches it. Seven of the nine rules were phase-specific
— margin governance during pricing, scope boundaries during take-off — and were
being paid for on every task regardless. They now live in `.claude/guides/`,
read when that phase starts.

## Before and after

| | Before | After |
|---|---:|---:|
| Files in the config surface | 60 | 57 |
| **Always-loaded lines** | **485** | **226** |
| `CLAUDE.md` | 51 | 67 |
| `AGENTS.md` | 51 (byte-identical duplicate) | 1 (`@CLAUDE.md`) |
| `.claude/rules/` | 9 files, 318 lines | 3 files, 158 lines |
| Memory dragged in by `@`-inline | 65 | 0 |
| `.claude/guides/` | — | 3 files, on demand |
| MCP servers with a doc | 0 of 8 | 8 of 8 |

`CLAUDE.md` grew by 16 lines. It replaced six hand-maintained lists of file
names — which duplicated a directory listing and were the likeliest thing in the
repo to go stale — with a routing table that stays true.

## What moved

| Was | Is now |
|---|---|
| `rules/file-safety.md` + `rules/human-in-the-loop.md` | `rules/00-core-constraints.md` |
| `rules/accuracy-trust.md` + `rules/pdf-verify-before-present.md` | `guides/extraction.md` |
| `rules/margin-governance.md` + `rules/p21-read-only.md` | `guides/pricing.md` |
| `rules/scope-boundaries.md` | `guides/takeoff.md` |
| `rules/data-stewardship.md` | `docs/data_stewardship.md` |
| `rules/auditability.md` | unchanged |
| `AGENTS.md` | `@CLAUDE.md` |

Skills, agents and commands were not touched — their triggers were already clear
and non-overlapping.

## Archived, not deleted

11 files in [`_archive/`](_archive/), each with a timestamp header saying where
it came from and why it moved. 313 lines of original rule text preserved
verbatim.

## Verified

- No `@`-inline in any always-loaded file. Agents and skills still inline
  freely — correct, because they load on demand.
- Every `.md` link in the config surface resolves.
- All 8 MCP servers documented in `.claude/mcp/README.md`.
- `139 passed, 13 skipped` across every test that reads an agent-config file
  (`test_scope_rules`, `test_margin_pointers`, `test_agent_definitions`,
  `tests/architecture/`, `test_autopilot`, `test_validate_project`).
- One test was broken by the move and fixed with your approval:
  `test_scope_rules.py` read `.claude/rules/scope-boundaries.md` directly.

**Still to confirm:** start a fresh session and check that the injected rule
payload is the three files in `.claude/rules/`, not nine. `.claude/guides/` is a
new directory and is assumed not to auto-load — every other `.claude/`
subdirectory (`agents/`, `skills/`, `memory/`, `commands/`) loads on demand, so
this is near-certain but unproven until a session starts.

## How to maintain this

**Before adding anything, ask where it loads.** That is the whole discipline.

| What you have | Where it goes |
|---|---|
| True for every task, and harm if broken | `.claude/rules/` — and add a hook. A rule nobody enforces is a suggestion. |
| Applies to one phase | `.claude/guides/`, plus a row in `rules/README.md` |
| Reference data, not an instruction | `.claude/memory/` |
| A capability invoked by a kind of task | `.claude/skills/<name>/SKILL.md` with a trigger in frontmatter |
| A repeatable user action | `.claude/commands/` |
| Project status, not agent behaviour | `docs/` |

Three habits worth keeping:

1. **Never edit the root file for a topic-specific rule.** `CLAUDE.md` is a map.
   If you are adding a constraint to it, it belongs somewhere else.
2. **State a constant once.** `0.75` was in four files, `US26D` in six, the
   Hager `0.29` in four. Point at the file that owns a number rather than
   restating it — a duplicated threshold is one that will disagree with itself.
3. **Never `@`-inline from a rule.** It drags the target into every session and
   defeats the point of it being on demand. From an agent or a skill it is fine.

## Left open for you

Three things were routed to human review rather than guessed at
([`AUDIT_FINDINGS.md`](AUDIT_FINDINGS.md) §6):

1. **Five memory files shadow live data.** `margin_sheet`,
   `finish_nomenclature`, `frame_depths`, `vendor_tiers` and `sales_tax_rules`
   restate what `mcp__reference__*` serves and what `/settings` now edits.
   Nothing keeps the two in step. Whether the markdown should be archived or
   kept as an offline fallback is a decision about what is authoritative for
   pricing — yours, not mine.
2. **`memory/process_flow.md`** — 6 lines. Stub, or deliberate pointer?
3. **`memory/estimator_profiles.md`** — should an agent behave differently
   depending on who is running it?

Also flagged, outside this audit's remit: `.claude/hooks/pre_tool_use.py` logs
`WARN: tool_session guard skipped: No module named 'cbc'` on every tool call —
its session guard is inert because the backend package is not on `PYTHONPATH`.
The `git-push` block still fires, so nothing is being let through.
