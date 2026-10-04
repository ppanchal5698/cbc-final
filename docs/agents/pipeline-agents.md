# Pipeline agents

A bid is worked by eleven subagents defined in `.claude/agents/`. Each one is a
markdown file: YAML frontmatter naming its model and its tool allow-list, then a
body of instructions.

The orchestrator dispatches them with the `Agent` tool when the provider
supports subagents. When it does not, one session walks the same phases alone —
see [Solo runs](#solo-runs) below.

## The roster

| Agent | Phase | Model | Writes |
|---|---|---|---|
| `intake-coordinator` | 0/1 | haiku | `extracted/scope_metadata.json` |
| `spec-scope-analyst` | 2 | haiku | `extracted/scope_summary.json` |
| `takeoff-engineer` | 3 | **sonnet** | patches to `extracted/line_items.json` |
| `frp-specialist` | 3b | haiku | `extracted/frp_takeoff.json` |
| `div10-specialist` | 3c | haiku | `extracted/div10_takeoff.json` |
| `product-matcher` | 4 | **sonnet** | `extracted/hardware_sets.json` |
| `pricing-engineer` | 4 | **sonnet** | `priced/line_items.json`, `priced/margin_applied.json` |
| `quote-builder` | 4/6 | haiku | `quotation.html` |
| `quality-reviewer` | 5 | haiku | `review/review_flags.json`, `review/review_summary.html` |
| `delivery-agent` | 6 | haiku | `review/quotation_email_draft.md` |
| `pricebook-ingestor` | side spine | haiku | catalog rows |

**The model split is the judgment split.** Three agents run on Sonnet because
their work is judgment that cannot be checked mechanically: deciding whether a
schedule cell really says what the parser thinks it says (`takeoff-engineer`),
deciding whether a catalog entry is the specified part or merely similar
(`product-matcher`), and choosing between five cost paths and defending the
choice (`pricing-engineer`). Everything else is mechanical and runs on Haiku.
`apps/backend/tests/system/test_agent_definitions.py` asserts this split holds.

`quote-builder` is defined but is **not** in the orchestrator chain — the worker
renders the quotation HTML itself. It exists for interactive and headless use.

## Tool allow-lists

The allow-list is the real boundary. Two are worth reading as statements of
intent:

- **`product-matcher` has no `pdf-tools` at all.** It matches openings that have
  already been extracted against the catalog; if it needed the drawing again,
  the take-off was wrong. Giving it PDF tools would let it quietly redo Phase 3.
- **`quality-reviewer` gets `artifact-storage` read-only** — `get_artifact` and
  `list_project_files`, no `save_artifact`. A reviewer that can rewrite the
  thing it is reviewing is not a reviewer.
- **`delivery-agent` has the narrowest list of all**: `Read`, `Write` and the
  four artifact-storage tools. No PDF tools, no catalog, no `Bash`. It prepares
  an email body and stops.

`pricing-engineer` has the widest: catalog, catalog-docs, pdf-tools, all six
calc-engine tools, all three p21-connector tools, artifact-storage, plus
`reference.get_manual_adders` and `get_margin_bands`.

`test_agent_definitions.py` cross-checks frontmatter against the body: every MCP
tool named in prose must be in the allow-list and belong to a real server, and
an agent told to run a script must have a tool that can run it.

## The delegation rule

`DELEGATION_RULE` lives in
`apps/backend/src/cbc/worker_kit/prompts.py` and is interpolated into the
orchestrator prompt when the provider supports subagents. It is the contract
between the orchestrator and the eleven agents.

Its substance is one idea, and it is the thing to understand about this
pipeline:

> **A subagent verifies a seeded artifact. It does not author one.**

The deterministic pre-take-off (`extraction/infrastructure/pretakeoff.py`)
parses the schedule in code first, before any token is spent, and writes
`extracted/door_schedule.extracted.json`. The subagent's job is to check that
against the sheets and correct it **field by field** through
`mcp__artifact-storage__propose_patch`, each patch carrying
`{source_page, excerpt}` evidence. A whole-file rewrite of a seeded checkpoint
is refused by the `checkpoint-propose-patch` hook rule.

The rest of the rule is mechanical: every `Agent` call must pass all three of
`description`, `subagent_type` and `prompt`; only the ten listed
`subagent_type` values are legal; verify output on disk between phases; wait for
each subagent's completion notification before reading what it owns; never
duplicate a delegated phase's work; never `cat` an agent definition file.

`test_prompts.py::test_the_delegation_rule_names_agents_that_exist` validates
the ten names against the files on disk.

### Ordering

```
intake-coordinator
  → spec-scope-analyst
    → takeoff-engineer ┐
      frp-specialist   ├─ concurrent when in scope
      div10-specialist ┘
        → product-matcher
          → pricing-engineer
            → quality-reviewer
              → delivery-agent
```

The three take-off agents run concurrently. Because a model asked to
parallelise does not reliably emit its `Agent` calls in one message, the worker
can instead run them as a **wave** — three prompts in one shared sandbox with
disjoint artifacts, parallelised by the worker rather than by the model. See
[`../backend/worker.md`](../backend/worker.md#waves).

While they run, `.claude/hooks` holds a lock per subagent so the orchestrator
cannot read a file its subagent is still writing. See
[`guardrails.md`](guardrails.md#the-session-guard).

## Solo runs

Not every provider can call the `Agent` tool. `SOLO_RULE` replaces
`DELEGATION_RULE` for those, and **inverts one instruction**: a solo run is told
it *must* read `.claude/agents/<name>.md` before each phase, because nothing
else loads them. A delegating run is told never to.

`apps/backend/tests/system/test_prompts.py` exists because a solo run once
received both sets of instructions at the same time.

Wave legs deliberately use `SOLO_RULE` too — the worker is doing the
parallelism, so there is no message in which the model can get the ordering
wrong.

## Skills, memory and commands

Three more directories under `.claude/`, all loaded on demand rather than every
session:

**`skills/`** (10) — a procedure an agent loads when its trigger matches:
`extract-door-schedule`, `extract-div10-takeoff`, `frp-takeoff`,
`scan-product-catalog`, `match-hardware-sets`, `price-line-item`,
`apply-margin`, `generate-quotation`, `validate-extraction`,
`reuse-prior-quote`. Two carry executable scripts —
`extract-door-schedule/scripts/parse_schedule.py` and
`generate-quotation/scripts/render_quote.py`.

**`memory/`** (13 files) — reference data, not instructions: `door_notation`,
`handing_codes`, `finish_nomenclature`, `fire_rating_rules`, `frame_depths`,
`margin_sheet`, `vendor_tiers`, `cost_sourcing_rules`, `sales_tax_rules`,
`manual_cutoff`, `estimator_profiles`, `project_context`, `process_flow`.

> Several of these shadow live data that the `reference` MCP server serves from
> Mongo and the estimator edits at `/settings` — `margin_sheet`,
> `finish_nomenclature`, `frame_depths`, `vendor_tiers`, `sales_tax_rules`.
> Where they disagree, the server is authoritative. Which copy should exist at
> all is an open question.

**`commands/`** (4) — the slash commands `/intake`, `/takeoff`, `/price`,
`/review`, each a thin pointer at the corresponding agent and the artifact to
save.

**`guides/`** (3) — phase guidance loaded on demand: `extraction.md`,
`pricing.md`, `takeoff.md`. Distinct from `.claude/rules/`, which is injected
into **every** session and therefore holds only two files. The routing policy is
in `.claude/rules/README.md`.

## See also

- What blocks what, and how: [`guardrails.md`](guardrails.md)
- What each phase actually does: [`../pipeline/README.md`](../pipeline/README.md)
- How the orchestrator prompt is built: [`../backend/worker.md`](../backend/worker.md#prompts)
