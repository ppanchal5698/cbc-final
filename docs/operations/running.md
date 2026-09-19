# Running the stack

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up -d --build
```

- Web UI — http://localhost:3000
- API health — http://127.0.0.1:8001/api/health

The root `docker-compose.yml` is a three-line shim that includes
`infra/docker-compose.yml`. Everything real is in the latter, which uses YAML
anchors (`x-app-env`, `x-domain-volumes`, `x-worker-env`, `x-api-health`) to
keep the API and worker environments identical.

## Services

| Service | Image / build | Exposure | Notes |
|---|---|---|---|
| `mongo` | `mongo:7` | `expose: 27017` | single-node replica set `rs0` |
| `mongo-init` | `mongo:7`, `restart: "no"` | — | idempotent `rs.initiate`, then exits |
| `clamav` | `clamav/clamav:stable` | `expose: 3310` | `start_period: 120s` — signature load is slow |
| `platform` | `apps/backend/Dockerfile`, target `api` | `expose: 8001` | the FastAPI service |
| `worker` | same Dockerfile, target `worker` | none | `WORKER_CLAIM_ALL=1` |
| `web` | `apps/web` | `expose: 3000` | Next.js standalone |
| `nginx` | `nginx:1.27-alpine` | **`80:80`, `443:443`** | the only published ports |
| `certbot` | `certbot/certbot:v3.1.0` | — | renew loop |
| `litellm` | `ghcr.io/berriai/litellm` | `expose: 4000` | profile `oss` |
| `mineru` | `infra/mineru` | — | profile `gpu`, needs an NVIDIA device |
| `parser` | worker image | none | profile `gpu`, `WORKER_DOMAIN=parsing` |
| `tunnel` | `cloudflared` | — | optional public URL |

**Only nginx publishes host ports.** Everything else is `expose:`, reachable
only from inside the compose network. That is why CI needs
`infra/docker-compose.ci.yml`, a two-entry overlay that publishes
`127.0.0.1:8001` and `127.0.0.1:3000` so Playwright can reach them without
standing up nginx — which would crash-loop anyway, because
`infra/nginx/default.conf` references
`/etc/letsencrypt/live/<MY_DOMAIN>/` as a literal unsubstituted placeholder.

Two profiles keep optional weight out of a default `up`: `oss` (the LiteLLM
gateway, for running against Ollama or OpenRouter) and `gpu` (MinerU plus a
dedicated parsing worker).

Networks: `default` (named `cbc-final`) and `llm` (named `cbc-final-llm`,
**`internal: true`**) — the latter is what `CBC_SANDBOX_NETWORK` points at, so a
sandboxed Claude run has no route to the internet.

### The Mongo replica set

A single-node replica set exists so multi-document transactions work locally,
which the code relies on (`MONGODB_TRANSACTIONS` defaults to 1).

`infra/docker/mongo-keyfile-entrypoint.sh` **copies** `/mongo-keyfile` to
`/data/keyfile`, chmods it 400 and chowns it to `mongodb`, then execs `mongod
--replSet rs0 --keyFile`. The copy is not incidental: a Windows bind mount
cannot hold mode 400, and `mongod` refuses a keyfile that is group- or
world-readable. If no keyfile is mounted the script generates 756 random bytes,
so a fresh clone comes up without a manual step.

`infra/docker/mongo-rs-init.sh` is idempotent — `rs.status().ok` exits 0,
otherwise it initiates and polls `myState == 1` for 30 seconds.

### Entrypoint

`infra/docker/entrypoint.sh` does three things before starting the app:

1. Merges `hasTrustDialogAccepted: true` for `/app` into `~/.claude.json`.
   **Without this every MCP call is silently denied**, and the symptom is an
   extraction that returns nothing rather than an error.
2. Asserts `/app/data/projects` and `/app/projects` are writable, with a named
   `chown` fix in the message when they are not.
3. Runs `python /app/scripts/bootstrap.py` unless `AUTO_BOOTSTRAP=0`.

## Environment

The full set is in `.env.example`. The ones that change behaviour rather than
credentials:

| Variable | Default | Effect |
|---|---|---|
| `WORKER_CLAIM_ALL` | `1` in compose | claim every domain except `parsing` |
| `WORKER_DOMAIN` | — | claim one domain; **unset and without CLAIM_ALL the worker refuses to start** |
| `WORKER_MAX_ATTEMPTS` | 3 | before a job is dead-lettered |
| `WORKER_JOB_TIMEOUT_SECONDS` | 3600 | 10800 for `run_full_pipeline` |
| `CLAUDE_SANDBOX` | `process` | `docker` runs each pass in its own container |
| `INTERNAL_AUTH` | `jwt` in compose, `token` in code | how the web tier authenticates to the API |
| `MALWARE_SCAN` | `clamd` | upload scanning |
| `STORAGE_BACKEND` | `local` | or `s3` |
| `MAX_UPLOAD_MB` | 200 | matched by nginx `client_max_body_size` and Next's `proxyClientMaxBodySize` |

`INTERNAL_AUTH` differing by layer is intentional — `token` is for local pytest,
`jwt` for anything with a network between the tiers — but it is easy to trip
over. With `jwt`, the web tier mints a 60-second HS256 token with
`aud: "platform"`; `INTERNAL_JWT_SECRET_PREVIOUS` exists so the secret can be
rotated without downtime.

> `MONGODB_READONLY_URI` appears in neither the compose file nor
> `.env.example`, but three MCP servers refuse to start without it. See
> [`../mcp/servers.md`](../mcp/servers.md#how-they-are-launched).

## The project directory

`cbc.shared.paths.storage_root()` resolves, in order: `CBC_PROJECTS_ROOT` (set
per job when a pass runs in a sandbox clone) → `STORAGE_ROOT` →
`data/projects`.

**There is no `projects/` at the repository root.** Rules, prompts and agent
files all say `projects/{name}/` — read that as the logical name for whatever
`storage_root()` currently resolves to. In a default checkout that is
`data/projects/{name}/`.

The layout, with the agent that writes each file:

```
uploads/raw/<bid-set>.pdf              immutable input — never written over
uploads/processed/mineru/<docId>/      MinerU block batches, p1-8.json, p9-16.json, …
uploads/final/                         delivery-agent copies

extracted/scope_metadata.json          intake-coordinator    schema-gated, blocking
extracted/scope_summary.json           spec-scope-analyst    schema-gated, blocking
extracted/door_schedule.json           takeoff-engineer      schema-gated, patch-only once seeded
extracted/door_schedule.extracted.json deterministic pre-take-off seed
extracted/frp_takeoff.json             frp-specialist
extracted/div10_takeoff.json           div10-specialist
extracted/hardware_sets.json           product-matcher
extracted/_matchcache.json             machine-written sidecars — leading underscore
extracted/_parse_status.json
extracted/_pipeline_context.json
extracted/_sheetmap.json
extracted/_visual_pages.json
extracted/*.json.manifest.json         cbc.shared.manifests sidecars

priced/line_items.json                 pricing-engineer      checkpoint
priced/margin_applied.json             pricing-engineer

review/review_flags.json               quality-reviewer (seeded by validation.review)
review/review_summary.html             quality-reviewer
review/quotation_email_draft.md        delivery-agent — a draft, never sent

quotation.html                         quote-builder / the worker
audit_trail.jsonl                      log_audit_trail.py, append-only, one record per tool call
.versions/<sha256>                     artifact-storage content blobs
.versions/versions.jsonl               append-only version index
.runs/<jobId>[-<phase>].log            worker run logs — one per wave leg
```

`data/projects/_scratch/` holds the per-job sandbox workspaces.

Only `wendys_acheson` is a real bid. The `e2e_*`, `alpha_tower`, `beta_plaza`,
`demo`, `thin` and `ordinary_work` directories are fixtures left by test runs.

## Reference data

`data/reference-library/` holds **seed JSON only** — margins, tax, adders,
finishes, frame depths, FRP constants, vendor tiers, special nets, stock lists.
The live values are in Mongo's `referenceData` collection, edited at `/settings`
and served by the `reference` MCP server. Where the two disagree, Mongo wins.

`data/pricebooks/` holds `index.json`, the Hager price book and multiplier PDFs,
and eleven markdown catalogs under `catalogs/` (ASI, Bobrick, Bradley, Gamco,
Hager, NGP, Nudo, Pemko, Rockwood, World Dryer, plus a cross-reference).

**Both directories are read-only during a pipeline run**, enforced by the
`protected-*` rules in `pre_delete_guard.py`. Updating them is a separate,
deliberate, human-initiated act — which is what the Ops-Hub price-book upload
is.

## Running the pipeline headlessly

```bash
bash workflows/run_full_pipeline.sh <project-name>
```

or one phase at a time:

```bash
bash workflows/phase3_takeoff.sh <project-name>
```

The eight `phaseN_*.sh` scripts are one-line wrappers over `workflows/_phase.sh`,
which holds the shared invocation. `run_phase` maps the agent to a job type and
**fails on an unknown agent rather than falling back to "everything"**, then
calls `python -m cbc.modules.ops.api.toolsets <job_type>` for the scope flags and
`python -m cbc.worker_kit.prompts` for the constraint preamble — so the headless
path and the Ops-Hub worker read from one source. Both had hand-copied
duplicates once, and they drifted.
`apps/backend/tests/system/test_headless_parity.py` asserts they stay in step.

Create a project first, if the Ops-Hub has not:

```bash
bash apps/backend/scripts/init_project.sh <project-name> <bid-set.pdf>
```

It scaffolds under the same root `storage_root()` resolves —
`CBC_PROJECTS_ROOT`, else `STORAGE_ROOT`, else `data/projects` — so a run and a
scaffold always agree about where a project lives.

`run_full_pipeline.sh` gates on `apps/backend/scripts/validate_project.py --all`
before spending a token: reference-library JSON parses, price books are present
and not stale, the MCP servers import, the hooks are in place.

## See also

- What CI runs and in what order: [`ci.md`](ci.md)
- What blocks a write: [`../agents/guardrails.md`](../agents/guardrails.md)
- How a job is claimed and run: [`../backend/worker.md`](../backend/worker.md)
