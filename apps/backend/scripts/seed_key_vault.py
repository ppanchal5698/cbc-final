"""Move the real secrets out of `.env` and into Azure Key Vault.

Easiest from inside the stack, where the vault URL and the emulator's
certificate are already set:

    docker compose -f infra/docker-compose.yml exec platform python /app/scripts/seed_key_vault.py --dry-run
    docker compose -f infra/docker-compose.yml exec platform python /app/scripts/seed_key_vault.py
    docker compose -f infra/docker-compose.yml up -d --force-recreate platform worker parser

Against a real vault, set KEY_VAULT_URL and sign in (`az login`); the client is
DefaultAzureCredential. Values are never printed - only names, lengths, counts.

## Why this is an allow-list and not "everything in .env"

The entrypoint loads every vault secret as process environment, and process
environment beats the compose `environment:` block. So a key pushed here does
not sit alongside the container's config, it *overrides* it.

The repo-root `.env` is a **native-run** file. It holds `CLAMD_HOST=127.0.0.1`,
`MALWARE_SCAN=off`, `INTERNAL_AUTH=token` and a `MONGODB_URI` pointing at
localhost - correct outside Docker, wrong inside it. Seeding the file wholesale
would silently switch off malware scanning and point every container at a
database that is not there. So: secrets move, host-shaped configuration stays.
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from cbc.shared import keyvault

# The mounted .env inside the container; the repo-root one natively.
ENV_FILE = Path("/app/.env")
if not ENV_FILE.exists():
    ENV_FILE = Path(__file__).resolve().parents[3] / ".env"

ASSIGNMENT = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")

# Key -> why it belongs in the secret store.
SEED: dict[str, str] = {
    # Credentials.
    "CLAUDE_CODE_OAUTH_TOKEN": "Claude subscription token",
    "ANTHROPIC_API_KEY": "Anthropic API key",
    "NVIDIA_NIM_API_KEY": "NVIDIA NIM key",
    "AWS_BEARER_TOKEN_BEDROCK": "Bedrock key",
    "PARSER_API_KEY": "LlamaParse key",
    "APP_SECRET_KEY": "app signing key",
    "AUTH_SECRET": "web session secret",
    "P21_API_KEY": "ERP API key",
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

# Connection strings stay in the environment, not the vault: the entrypoint
# needs the database and the vault's own URL before it can read anything, and
# compose already points each one at its emulator.
HOST_SHAPED = {
    "MONGODB_URI": "compose points it at the database",
    "MONGODB_READONLY_URI": "compose points it at the database",
    "MONGO_ROOT_PASSWORD": "the emulator is created with it before the vault is read",
    "AZURE_STORAGE_CONNECTION_STRING": "compose points it at Blob Storage",
    "KEY_VAULT_URL": "the vault cannot hold its own address",
    "CLAMD_HOST": "127.0.0.1 natively, `clamav` in compose",
    "MALWARE_SCAN": "off natively, clamd in compose",
    "STORAGE_ROOT": "host path",
    "PRICEBOOK_DIR": "host path",
    "REFERENCE_DIR": "host path",
    "TEMPLATES_DIR": "host path",
    "STORAGE_BACKEND": "compose sets it",
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report what would move, contact nothing")
    parser.add_argument("--env-file", type=Path, default=ENV_FILE)
    args = parser.parse_args()

    clash = sorted(set(SEED) & keyvault.SHARED_WITH_WEB)
    if clash:
        raise SystemExit(f"set on the `web` service too, so seeding them breaks the UI: {clash}")

    env = read_assignments(args.env_file)
    moving = {k: v for k, v in env.items() if k in SEED and v}
    staying = sorted(k for k in env if k not in SEED)

    print(f"{len(env)} assignments in {args.env_file}")
    print(f"\nmoving to Key Vault ({len(moving)}):")
    for key in sorted(moving):
        print(f"  {key:34s} {len(moving[key]):>4} chars  - {SEED[key]}")
    print(f"\nstaying in .env ({len(staying)}):")
    for key in staying:
        why = HOST_SHAPED.get(key) or ("set on web too" if key in keyvault.SHARED_WITH_WEB else "not a secret")
        print(f"  {key:34s} {why}")

    if args.dry_run or not moving:
        print("\nnothing sent." if args.dry_run else "\nnothing to seed.")
        return 0

    url = os.environ.get("KEY_VAULT_URL", "").strip()
    if not url:
        raise SystemExit("KEY_VAULT_URL is not set - run this inside the platform container, or export it")
    vault = keyvault.client(url)
    for key, value in sorted(moving.items()):
        vault.set_secret(keyvault.secret_name(key), value, content_type=SEED[key])
    print(f"\npushed {len(moving)} secret(s) to {url}")
    print(
        "\nNext: docker compose -f infra/docker-compose.yml up -d --force-recreate platform worker parser\n"
        "Expect `[entrypoint] N secret(s) from Key Vault` in their logs before clearing those keys from .env."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
