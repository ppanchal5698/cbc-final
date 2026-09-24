"""Move the real secrets out of `.env` and into Infisical.

Run on the host, once, after creating a machine identity in the Infisical UI:

    python scripts/migrate_secrets_to_infisical.py --dry-run
    python scripts/migrate_secrets_to_infisical.py

Reads the identity from `infra/infisical-client.env`, creates the project and
environment if they are missing, pushes the secrets, and writes the resulting
project id back into that file. Values are never printed — only names, lengths
and counts.

## Why this is an allow-list and not "everything in .env"

`infisical run` sets these as process environment, and process environment beats
the compose `environment:` block. So a key pushed here does not sit alongside
the container's config, it *overrides* it.

That matters because the repo-root `.env` is a **native-run** file. It holds
`CLAMD_HOST=127.0.0.1`, `MALWARE_SCAN=off`, `INTERNAL_AUTH=token` and a
`MONGODB_URI` pointing at localhost — correct outside Docker, wrong inside it,
where compose sets `clamav`, `clamd` and `mongo`. Migrating the file wholesale
would silently switch off malware scanning and point every container at a
database that is not there.

So: secrets move, host-shaped configuration stays. MIGRATE lists what moves and
why; everything else is reported as deliberately left behind.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
CLIENT_FILE = ROOT / "infra" / "infisical-client.env"

ASSIGNMENT = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")

# Key -> why it belongs in the secret store.
MIGRATE: dict[str, str] = {
    # Credentials.
    "CLAUDE_CODE_OAUTH_TOKEN": "Claude subscription token",
    "ANTHROPIC_API_KEY": "Anthropic API key",
    "NVIDIA_NIM_API_KEY": "NVIDIA NIM key",
    "AWS_BEARER_TOKEN_BEDROCK": "Bedrock key",
    "PARSER_API_KEY": "LlamaParse key",
    "APP_SECRET_KEY": "app signing key",
    "MONGO_ROOT_PASSWORD": "database password",
    "AUTH_SECRET": "web session secret",
    "P21_DSN": "ERP connection string",
    "P21_USER": "ERP user",
    "P21_PASSWORD": "ERP password",
    # Not credentials, but read env-first by the application and safe in any
    # environment - no host paths, no hostnames.
    "WORKER_MAX_COST_USD_PER_DAY": "spend cap",
    "WORKER_MAX_COST_USD_PER_PROJECT": "spend cap",
    "PARSER_TIER": "LlamaParse tier",
    "PARSER_LANG": "LlamaParse language",
    "PARSER_WINDOW_PAGES": "parse window size",
    "PARSER_WINDOW_CONCURRENCY": "parse windows in flight",
    "PARSER_WINDOW_TIMEOUT_SECONDS": "parse window timeout",
    "PARSER_WAIT_MAX_SECONDS": "parse wait ceiling",
    "PRICEBOOK_DEV_FRESHNESS": "price-book freshness override",
}

# Shared with the `web` service, which compose configures and the CLI cannot
# reach - web is a Next.js image with no Infisical CLI in it.
#
# Injecting one of these overrides the compose value on platform/worker/parser
# ONLY, so the backend starts expecting a token the frontend does not send and
# every server-side render 401s with "Bearer token required". That is not
# theoretical: migrating the first two broke the whole UI with React #441.
#
# Derived, not guessed - `docker compose config` lists exactly four keys set on
# both `web` and a backend service, and test_infisical_wiring.py re-derives them
# and fails if any lands in MIGRATE.
SHARED_WITH_WEB = {
    "INTERNAL_API_TOKEN": "web sends it; injecting it here only moves the backend",
    "INTERNAL_JWT_SECRET": "web signs with it; injecting it here only moves the backend",
    "INTERNAL_JWT_SECRET_PREVIOUS": "rotation pair for the above",
    "INTERNAL_AUTH": "token natively, jwt in compose",
    "APP_ENV": "compose sets it on both",
}

# Named so the report can say *why* rather than just omitting them.
HOST_SHAPED = {
    "MONGODB_URI": "points at localhost for native runs; compose sets `mongo`",
    "MONGODB_DB": "compose sets it",
    "MONGODB_READONLY_URI": "derived at start-up when empty",
    "CLAMD_HOST": "127.0.0.1 natively, `clamav` in compose",
    "CLAMD_PORT": "compose sets it",
    "MALWARE_SCAN": "off natively, clamd in compose",
    "MALWARE_SCAN_REQUIRED": "compose sets it",
    "INTERNAL_AUTH": "token natively, jwt in compose",
    "STORAGE_ROOT": "host path",
    "PRICEBOOK_DIR": "host path",
    "REFERENCE_DIR": "host path",
    "TEMPLATES_DIR": "host path",
    "STORAGE_BACKEND": "compose sets it",
    "API_BIND": "native run only",
    "CLAUDE_BIN": "native run only",
    "AUTO_BOOTSTRAP": "native run only",
    "APP_ENV": "compose sets it",
    "CORS_ORIGINS": "compose sets it",
    "NEXTAUTH_URL": "compose sets it",
    "SERVICE_AUDIENCE": "differs per service; compose sets it",
    "MAX_UPLOAD_MB": "compose sets it",
    "PIPELINE_DEBOUNCE_SECONDS": "compose sets it",
    "WORKER_POLL_SECONDS": "compose sets it",
    "WORKER_CONCURRENCY": "differs per service; compose sets it",
    "WORKER_JOB_TIMEOUT_SECONDS": "compose sets it",
    "WORKER_MAX_ATTEMPTS": "compose sets it",
    "WORKER_MAX_TURNS": "compose sets it",
    "WORKER_RETRY_BASE_SECONDS": "compose sets it",
}


def read_assignments(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        found = ASSIGNMENT.match(line)
        if not found:
            continue
        raw = found.group(2).strip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
            raw = raw[1:-1]
        values[found.group(1)] = raw
    return values


def call(url: str, *, token: str | None = None, payload: dict | None = None,
         method: str | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"))
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as error:
        detail = error.read().decode()[:400]
        raise SystemExit(f"{method or 'POST'} {url} -> {error.code}\n{detail}") from None
    except urllib.error.URLError as error:
        raise SystemExit(f"cannot reach {url}: {error.reason}") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would move, contact nothing")
    parser.add_argument("--project-name", default="CBC Estimating Copilot")
    args = parser.parse_args()

    env = read_assignments(ENV_FILE)
    client = read_assignments(CLIENT_FILE)

    moving = {k: v for k, v in env.items() if k in MIGRATE and v}
    empty = sorted(k for k in env if k in MIGRATE and not env[k])
    staying = sorted(k for k in env if k not in MIGRATE)

    clash = sorted(set(MIGRATE) & set(SHARED_WITH_WEB))
    if clash:
        raise SystemExit(
            "these are set on the `web` service too, so injecting them only moves "
            f"the backend and breaks the UI: {clash}"
        )

    print(f"{len(env)} assignments in .env")
    print(f"\nmoving to Infisical ({len(moving)}):")
    for key in sorted(moving):
        print(f"  {key:34s} {len(moving[key]):>4} chars  - {MIGRATE[key]}")
    if empty:
        print(f"\nlisted but empty, skipped ({len(empty)}): {', '.join(empty)}")
    print(f"\nstaying in .env ({len(staying)}) - host-shaped or compose-owned:")
    for key in staying:
        why = SHARED_WITH_WEB.get(key) or HOST_SHAPED.get(key) or "not a secret"
        print(f"  {key:34s} {why}")

    if args.dry_run:
        print("\n--dry-run: nothing sent.")
        return 0
    if not moving:
        print("\nnothing to migrate.")
        return 0

    api = (client.get("INFISICAL_API_URL") or "http://localhost:8080").rstrip("/")
    # The containers reach Infisical as http://infisical:8080; this script runs
    # on the host, where that name does not resolve.
    if "//infisical:" in api:
        api = "http://localhost:8080"
    client_id = client.get("INFISICAL_UNIVERSAL_AUTH_CLIENT_ID", "")
    client_secret = client.get("INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        print(
            f"\nNo machine identity in {CLIENT_FILE.relative_to(ROOT)}.\n"
            "In the Infisical UI: Organization -> Access Control -> Identities ->\n"
            "Create identity, auth method Universal Auth, org role Admin (it has to\n"
            "create the project). Put the client ID and client secret in that file,\n"
            "then run this again.",
            file=sys.stderr,
        )
        return 1

    token = call(f"{api}/api/v1/auth/universal-auth/login",
                 payload={"clientId": client_id, "clientSecret": client_secret},
                 )["accessToken"]
    print(f"\nauthenticated against {api}")

    project_id = client.get("INFISICAL_PROJECT_ID", "")
    if not project_id:
        created = call(f"{api}/api/v2/workspace", token=token,
                       payload={"projectName": args.project_name,
                                "shouldCreateDefaultEnvs": True})
        project = created.get("project", created)
        project_id = project.get("id") or project.get("_id")
        print(f"created project {args.project_name!r} -> {project_id}")
    else:
        print(f"using existing project {project_id}")

    slug = client.get("INFISICAL_ENV_SLUG") or "prod"
    try:
        call(f"{api}/api/v1/projects/{project_id}/environments/slug/{slug}", token=token)
        print(f"environment {slug!r} already exists")
    except SystemExit:
        call(f"{api}/api/v1/projects/{project_id}/environments", token=token,
             payload={"name": slug, "slug": slug})
        print(f"created environment {slug!r}")

    call(f"{api}/api/v3/secrets/batch/raw", token=token,
         payload={
             "workspaceId": project_id,
             "environment": slug,
             "secretPath": client.get("INFISICAL_SECRET_PATH") or "/",
             "secrets": [
                 {"secretKey": k, "secretValue": v, "secretComment": MIGRATE[k]}
                 for k, v in sorted(moving.items())
             ],
         })
    print(f"pushed {len(moving)} secrets to {slug}")

    if not client.get("INFISICAL_PROJECT_ID"):
        text = CLIENT_FILE.read_text(encoding="utf-8")
        text = re.sub(r"(?m)^INFISICAL_PROJECT_ID=.*$",
                      f"INFISICAL_PROJECT_ID={project_id}", text)
        CLIENT_FILE.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote INFISICAL_PROJECT_ID into {CLIENT_FILE.relative_to(ROOT)}")

    print(
        "\nNext:\n"
        "  docker compose -f infra/docker-compose.yml up -d --force-recreate "
        "platform worker parser\n"
        "  docker logs cbc-final-worker | head -3\n"
        "Expect: [entrypoint] secrets from Infisical: project ..., env "
        f"{slug}, path /\n"
        "Only once you see that line should you clear these keys from .env - it is "
        "the fallback."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
