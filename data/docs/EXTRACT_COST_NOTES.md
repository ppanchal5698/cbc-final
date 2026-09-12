# Extract cost notes (operator)

## Agent subagents and prompt cache

`extract_bid_set` is one Claude Code `claude --print` session, but **Agent tool
subagents are separate billed contexts**. Do not assume the four phases
(intake → scope → takeoff → FRP) share one cached prefix.

Measure reality from `runMetrics` after each job:

- `tokens.cacheRead` / `tokens.cacheCreate`
- `tokens.cacheHitRatio` = `cacheRead / (cacheRead + cacheCreate)` when either is non-zero
- `tokens.coldPrefixWrites` / `coldPrefixTokens` — large cold writes usually mean a
  subagent re-instantiated system/tools context

If `cacheHitRatio` is low and `coldPrefixWrites` tracks Agent launches, the
lever is smaller Agent prompts (page lists + JSON paths only — already in the
EXTRACT prompt), not “one session” folklore.

`stragglerMerge` is stored on the metrics document for dashboards.

## Spend ops and budgets

- **Worker claim caps:** `WORKER_MAX_COST_USD_PER_DAY` / `WORKER_MAX_COST_USD_PER_PROJECT`
  leave jobs queued when `runMetrics` spend is at the cap (see `/ops/spend`).
- **LiteLLM soft budget:** with the `oss` compose profile, set `LITELLM_MAX_BUDGET`
  to the same USD number as the daily worker cap. The gateway rejects further calls
  after proxy spend hits the limit; claim caps still stop new jobs from starting.
- **Mongo HA:** compose uses a single-node `rs0` so multi-document transactions work
  locally. Production HA is a managed cluster and a connection-string swap — not a
  multi-member replica set defined in this repo.

## Page circuit breaker

`EXTRACT_MAX_PDF_PAGES` (default 400) sums **all** PDFs under `uploads/raw/` on
**every** `extract_bid_set`, including straggler merge follow-ups. Late uploads
that push the set over the cap fail with `extract_too_large` before Claude runs.

## Message Batches API — deferred

`match_and_price` and `build_proposal` run through Claude Code + Agent + MCP tool
loops (`claude_cli.run_claude`). Anthropic Message Batches is a one-shot Messages
API product and **cannot host** Agent/MCP multi-turn work.

To get Batch discounts later: rewrite those phases into deterministic Python (or
narrow `LLMClient` JSON steps) and only then batch the text/JSON calls. That
replaces agents; it does not wrap them.
