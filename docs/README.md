# Documentation

CBC Estimating Copilot — bid documents in, priced proposal out, with a human
approving before anything leaves the building.

## Start here

| If you want to… | Read |
|---|---|
| understand the system in one sitting | [`system-design.md`](system-design.md) |
| see how data moves through it | [`data-flow-diagrams.md`](data-flow-diagrams.md) |
| know what a phase actually does | [`pipeline/README.md`](pipeline/README.md) |
| run it locally | [`operations/running.md`](operations/running.md) |

## By area

**Backend** — one FastAPI process, seven modules, one worker.

- [`backend/modules.md`](backend/modules.md) — what each module owns, the
  dependency graph, and the seven boundary rules a test enforces
- [`backend/api.md`](backend/api.md) — how 91 paths get assembled, what runs at
  startup, and the import order that breaks `.env` if you get it wrong
- [`backend/worker.md`](backend/worker.md) — job claiming and fencing, retries,
  defer gates, how a Claude pass is invoked, and how prompts are built

**Frontend** — the Ops-Hub.

- [`frontend/routes.md`](frontend/routes.md) — every screen, both data paths,
  and which domain rules are mirrored from the backend
- [`frontend/design-system.md`](frontend/design-system.md) — the token set, the
  `.app-shell` grid, and how a page plugs into it

**The pipeline** — eight phases, eleven agents.

- [`pipeline/README.md`](pipeline/README.md) — the phase table, scope
  boundaries, and the rules every phase obeys
- One document per phase:
  [0/1](pipeline/phase-0-1-intake.md) ·
  [2](pipeline/phase-2-spec-scope.md) ·
  [3](pipeline/phase-3-takeoff.md) ·
  [3b](pipeline/phase-3b-frp.md) ·
  [3c](pipeline/phase-3c-div10.md) ·
  [4](pipeline/phase-4-pricing.md) ·
  [5](pipeline/phase-5-review.md) ·
  [6](pipeline/phase-6-delivery.md)
- [`agents/pipeline-agents.md`](agents/pipeline-agents.md) — the roster, the
  model split, and the delegation rule
- [`agents/guardrails.md`](agents/guardrails.md) — every hook, every rule tag,
  and what each one blocks

**Tools and data**

- [`mcp/servers.md`](mcp/servers.md) — all eight MCP servers, their tools, and
  how read-only is enforced (it differs per server)
- [`collections.mongodb.md`](collections.mongodb.md) — 32 collections, field by
  field, with indexes and provenance conventions

**Operations**

- [`operations/running.md`](operations/running.md) — compose services, the
  environment, and the project directory layout
- [`operations/ci.md`](operations/ci.md) — the three CI jobs and what the
  architecture tests guard
- [`data_stewardship.md`](data_stewardship.md) — open items, including the
  ownership gap that is still unassigned

## Four things worth knowing early

**A subagent verifies a seeded artifact; it does not author one.** A
deterministic parser writes the door schedule in code before any token is spent.
The agent checks it against the sheets and corrects it field by field with
page-cited patches. Whole-file rewrites of a seeded checkpoint are blocked by a
hook.

**Nothing is sent.** The pipeline ends at a draft on disk and the literal
message `Draft ready for estimator review`. `pre_send_quote.py` blocks every
mail path and any tool whose name contains send, email or mail — for every
agent, at every phase, regardless of permission mode.

**Flag, do not guess.** A missing attribute is `null` and flagged, never
inferred from a neighbouring row. Match confidence below 0.75 goes to review. A
cost with no defensible source is `MANUAL` with a plain-language reason — not an
error, and not a guess.

**Every number names its source.** Extracted records carry `source_page`,
`bbox` and `page_size`; priced lines carry `cost_source`, the multiplier tier
and the price-book version. A page number alone is not traceability — it names a
sheet someone still has to search by eye.

## Conventions in these docs

`projects/{name}/` is the logical name for the project directory. On disk it
resolves through `storage_root()` — `CBC_PROJECTS_ROOT`, then `STORAGE_ROOT`,
then `data/projects`. **There is no `projects/` at the repository root.**

Paths in backticks are real and resolvable from the repository root.
`apps/backend/tests/system/test_traceability_doc.py` walks every markdown file
here and fails if one of them does not exist, so a path in these docs is either
correct or the build is red.
