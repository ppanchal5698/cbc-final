# CBC Estimating Copilot (modular monolith)

Bid documents in, priced proposal out. Live API and workers:
[`apps/backend`](apps/backend) — the compose service is still named `platform`,
on port 8001. Compose runs one `worker` with `WORKER_CLAIM_ALL=1` (a local run
may set `WORKER_DOMAIN` instead). Web: [`apps/web`](apps/web).

```bash
docker compose -f infra/docker-compose.yml up -d --build
```

## Where things are

There is no separate doc set; the code and its tests are the reference.

| | |
|---|---|
| Modules and the layering rule | [`apps/backend/src/cbc/modules`](apps/backend/src/cbc/modules), enforced by [`tests/architecture/test_layering.py`](apps/backend/tests/architecture/test_layering.py) |
| Routes, startup, middleware | [`apps/backend/src/cbc/app/main.py`](apps/backend/src/cbc/app/main.py) |
| Job lifecycle and Claude passes | [`ops/api/worker.py`](apps/backend/src/cbc/modules/ops/api/worker.py), [`ops/api/claude_pass.py`](apps/backend/src/cbc/modules/ops/api/claude_pass.py) |
| Estimating process and its prompts | [`worker_kit/prompts.py`](apps/backend/src/cbc/worker_kit/prompts.py) and [`.claude/agents/`](.claude/agents) |
| Running it | [`infra/docker-compose.yml`](infra/docker-compose.yml), [`apps/backend/README.md`](apps/backend/README.md) |

## Agent configuration

Four directories, each loaded differently. **Read
[`.claude/rules/README.md`](.claude/rules/README.md) before adding to any of
them** — it says which is which and why it matters.

| Directory | Loaded |
|---|---|
| `.claude/rules/` | **every session** — core constraints and auditability only |
| `.claude/guides/` | on demand — one per phase (extraction, pricing, take-off) |
| `.claude/memory/` | on demand — reference data (door notation, finishes, tiers, margins) |
| `.claude/skills/` | when a skill's trigger matches |
| `.claude/agents/` | when that subagent is dispatched |
| `.claude/commands/` | `/intake` `/takeoff` `/price` `/review` |

Do not `@`-inline a guide, memory file or skill from a rule — that drags it into
every session and defeats the point of it being on demand.

## Bid pipeline

`DELEGATION_RULE` lives in
[`apps/backend/src/cbc/worker_kit/prompts.py`](apps/backend/src/cbc/worker_kit/prompts.py)
and is the source of truth for the order:

```
intake-coordinator → spec-scope-analyst → takeoff-engineer
  → frp-specialist / div10-specialist   (when in scope)
  → product-matcher → pricing-engineer → quality-reviewer → delivery-agent
```

Side spine: `pricebook-ingestor`. `quote-builder` exists for interactive and
headless use — the worker renders the quotation HTML itself, so it is not in the
orchestrator list.

Judgment agents (`takeoff-engineer`, `product-matcher`, `pricing-engineer`) run
on Sonnet. Mechanical agents run on Haiku.

## MCP servers

Configured in [`.mcp.json`](.mcp.json); what each one is for is in
[`.claude/mcp/README.md`](.claude/mcp/README.md). `p21-connector` is read-only,
`catalog` is read-only, and `artifact-storage` is the only writer — it writes
under `CBC_PROJECTS_ROOT`.

The interactive allow-list is in `.claude/settings.json`. Workers skip
permission prompts; PreToolUse hooks still fire.
