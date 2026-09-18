<!-- ARCHIVED 2026-09-18T12:39:24Z by the agent-config audit.
     Original location: AGENTS.md
     It was byte-identical to CLAUDE.md; replaced with a one-line pointer. -->

# CBC Estimating Copilot (modular monolith)

Live API + workers: [`apps/backend`](apps/backend). Compose service name
remains `platform` on port 8001. Compose runs one `worker` with
`WORKER_CLAIM_ALL=1` (local runs may still set `WORKER_DOMAIN`).

Web: [`apps/web`](apps/web). Data model: [`docs/collections.mongodb.md`](docs/collections.mongodb.md).
Runtime: [`docs/app_lifecycle.md`](docs/app_lifecycle.md). Architecture:
[`docs/architecture.md`](docs/architecture.md). Process:
[`docs/cbc_process_flow.md`](docs/cbc_process_flow.md).

Run: `docker compose -f infra/docker-compose.yml up -d --build`

Rules under `.claude/rules/` load automatically. Do not `@`-inline them (or
memory/skills) into this file — cite paths in plain text.

## Bid pipeline agents (`.claude/agents/`)

Orchestrator `DELEGATION_RULE` (in `apps/backend/src/cbc/worker_kit/prompts.py`):
`intake-coordinator` → `spec-scope-analyst` → `takeoff-engineer` +
`frp-specialist` / `div10-specialist` when in scope → `product-matcher` →
`pricing-engineer` → `quality-reviewer` → `delivery-agent`. Side spine:
`pricebook-ingestor`. `quote-builder` exists for interactive/headless use;
the worker renders quotation HTML, so it is not in the orchestrator list.

Judgment agents (`takeoff-engineer`, `product-matcher`, `pricing-engineer`)
use Sonnet. Mechanical agents use Haiku.

## Skills, rules, memory

Skills in `.claude/skills/`: `extract-door-schedule`, `extract-div10-takeoff`,
`frp-takeoff`, `scan-product-catalog`, `match-hardware-sets`, `price-line-item`,
`apply-margin`, `generate-quotation`, `validate-extraction`, `reuse-prior-quote`.

Rules in `.claude/rules/`: `accuracy-trust`, `auditability`, `data-stewardship`,
`file-safety`, `human-in-the-loop`, `margin-governance`, `p21-read-only`,
`pdf-verify-before-present`, `scope-boundaries`.

Memory in `.claude/memory/`: `cost_sourcing_rules`, `door_notation`,
`estimator_profiles`, `finish_nomenclature`, `fire_rating_rules`, `frame_depths`,
`handing_codes`, `manual_cutoff`, `margin_sheet`, `process_flow`,
`project_context`, `sales_tax_rules`, `vendor_tiers`.

Slash commands in `.claude/commands/`: `/intake`, `/takeoff`, `/price`, `/review`.

## MCP servers (`.mcp.json`)

`bid-docs`, `catalog`, `catalog-docs`, `pdf-tools`, `reference`, `calc-engine`,
`p21-connector` (read-only), `artifact-storage` (only writer, under
`CBC_PROJECTS_ROOT`). Interactive allow-list lives in `.claude/settings.json`.
Workers skip permission prompts; PreToolUse hooks still fire.
