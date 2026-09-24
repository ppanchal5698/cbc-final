# Secrets — Infisical

Self-hosted [Infisical](https://github.com/Infisical/infisical) is the secret
store for the backend services. It is **opt-in**: nothing changes until you
configure it, and if it is down the stack falls back to the repo-root `.env`
exactly as it did before.

## Why this needed no application code

Every credential in this system already resolves **process environment first,
then `.env`, then the database** — `provider.build_env`, `parsing_config.resolve`
and `cost_budget._cap` all do it, and the Settings screen already renders a
value sourced from the environment as locked.

So the whole integration is: get the secrets into the process environment before
Python starts. [`infra/docker/entrypoint.sh`](../../infra/docker/entrypoint.sh)
re-execs itself under `infisical run`, and the existing precedence does the rest.
A secret served by Infisical simply wins, and the Settings screen correctly
shows it as no longer editable from there.

## What is covered

| | Secrets from |
|---|---|
| `platform`, `worker`, `parser` | Infisical, falling back to `.env` |
| `web`, `litellm`, `mongo`, `nginx` | compose `environment:` — see [the gap](#what-is-not-covered) |

## Setup

### 1. Server bootstrap credentials

Infisical's own keys cannot live inside Infisical. They go in a file of their
own — not the app's `.env`, because the container replacing your secrets has no
business holding them.

```bash
cp infra/infisical.env.example infra/infisical.env
```

Fill in `ENCRYPTION_KEY` and `AUTH_SECRET`. **Generate them.** The values in
Infisical's published `.env.example` are public, and a store encrypted with a
public key is not encrypted. The file lists the commands; on Windows:

```powershell
-join ((1..16 | ForEach-Object { '{0:x2}' -f (Get-Random -Maximum 256) }))
[Convert]::ToBase64String((1..32 | ForEach-Object { [byte](Get-Random -Maximum 256) }))
```

Back `ENCRYPTION_KEY` up somewhere outside this stack. Change it after secrets
exist and they are unreadable.

### 2. Start it

```bash
docker compose -f infra/docker-compose.yml --profile secrets up -d
```

Without `--profile secrets` the Infisical services do not start, which is why
the documented `docker compose -f infra/docker-compose.yml up -d --build` is
unaffected.

Open <http://localhost:8080>, create the admin account, create a project.

### 3. Machine identity

Organization → Access Control → Identities → create, **Universal Auth**. Grant
it access to the project. **Read-only** — it is mounted into three containers,
so anything it can write, a compromised worker can write. The client secret is
shown once.

```bash
cp infra/infisical-client.env.example infra/infisical-client.env
```

Fill in `INFISICAL_PROJECT_ID` (Project → Settings), the client ID and the
client secret.

### 4. Move the secrets in

```bash
python scripts/migrate_secrets_to_infisical.py --dry-run
python scripts/migrate_secrets_to_infisical.py
```

It creates the project and environment if they are missing, pushes the secrets,
and writes `INFISICAL_PROJECT_ID` back into the client file. Values are never
printed — only names and lengths.

**It is an allow-list, not a copy of `.env`.** `infisical run` sets these as
process environment, which *overrides* the compose `environment:` block — so a
key pushed here replaces the container's config rather than sitting beside it.
The repo-root `.env` is a native-run file: its `MONGODB_URI` points at
`localhost` and carries no `replicaSet`, and it sets `CLAMD_HOST=127.0.0.1`,
`MALWARE_SCAN=off` and `INTERNAL_AUTH=token`. Pushing it wholesale would point
every container at a database that is not there, disable transactions, and turn
off malware scanning. Secrets move; host-shaped configuration stays. The script
prints both lists with a reason for each.

To add a key by hand, use the same variable name as `.env` — that is the name it
lands under in the process environment. The ones that matter:

| | |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude subscription token |
| `ANTHROPIC_API_KEY`, `NVIDIA_NIM_API_KEY`, `AWS_BEARER_TOKEN_BEDROCK` | whichever provider you use |
| `PARSER_API_KEY` | LlamaParse |
| `APP_SECRET_KEY`, `INTERNAL_API_TOKEN`, `INTERNAL_JWT_SECRET` | service auth |
| `P21_*` | the read-only ERP connector |
| `WORKER_MAX_COST_USD_PER_DAY`, `WORKER_MAX_COST_USD_PER_PROJECT` | spend caps |

Then restart the three services:

```bash
docker compose -f infra/docker-compose.yml up -d --force-recreate platform worker parser
```

`docker logs cbc-final-worker` should open with:

```
[entrypoint] secrets from Infisical: project <id>, env prod, path /
```

Once a secret is served from Infisical you can delete it from `.env`. Keep
`.env` working until you have confirmed that line, because it is the fallback.

## Rotating

Change the value in the Infisical UI and restart the service. Injection happens
at container start, so a rotation needs a restart — it does not need an image
rebuild, a file edit, or a `docker compose` config change.

## When it fails

Deliberately fail-open. Infisical unreachable, credentials missing or login
refused all log a line and continue on `.env`:

```
[entrypoint] Infisical login failed - falling back to .env
[entrypoint] Infisical configured but no token - using .env
```

A secrets manager that takes the whole stack down when it blinks is a worse
outage than the one it prevents. The trade is explicit: a stale `.env` can serve
a secret you thought you had rotated. If that matters more than uptime in your
deployment, delete the fallback — remove the two `echo` branches in the
entrypoint and let the `exec` be unconditional.

`tests/system/test_infisical_wiring.py` starts the real entrypoint against a
stub CLI that fails, and asserts the container still comes up.

## What is not covered

`web`, `litellm`, `mongo` and `nginx` get their configuration from compose
`environment:` interpolation, which happens on the host before any container
exists — the CLI cannot reach it. Those values are at their compose defaults.

Two notes on that, both deliberate:

- Compose does **not** read the repo-root `.env`. Its project directory is
  `infra/`, and that directory holds no env file of its own. Do not "fix" this with
  `--env-file ../.env`: the root file holds native-run values
  (`CLAMD_HOST=127.0.0.1`, `MALWARE_SCAN=off`, `INTERNAL_AUTH=token`) that are
  wrong inside compose, and passing it changes 11 settings across four services.
- To source those from Infisical, export them on the host first:

  ```bash
  infisical export --format=dotenv > infra/.env.generated
  docker compose --env-file infra/.env.generated -f infra/docker-compose.yml up -d
  ```

  That writes plaintext secrets to disk, which is what this was meant to avoid.
  Extending injection to `web` means installing the CLI in its image too.

## The CLI

Pinned by version and sha256 in
[`apps/backend/Dockerfile`](../../apps/backend/Dockerfile), not installed by
Infisical's documented `curl … | bash`. The binary that reads every credential
this system owns is a poor place for an unpinned remote script, and a checksum
is what makes the build auditable (NFR-3).

To bump it, take the version and both digests from the
[releases page](https://github.com/Infisical/infisical/releases) — tag
`infisical-cli/vX.Y.Z`, asset `checksums.txt`.
