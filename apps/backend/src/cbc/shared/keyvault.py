"""Secrets from Azure Key Vault, put into the environment before the process starts.

infra/docker/entrypoint.sh runs ``python -m cbc.shared.keyvault -- <command>``:
every enabled secret in KEY_VAULT_URL becomes an environment variable, then the
command is exec'd - what ``infisical run`` did before. A vault value overrides
the environment, so the vault is the source of truth wherever it is configured;
scripts/seed_key_vault.py decides what goes in it.

Locally the vault is Floci's emulator. AZURE_EMULATOR_CA names its self-signed
certificate, and only then does this accept the emulator's terms: any bearer
token, and a challenge that does not name vault.azure.net. In production that
variable is unset and the client is the stock one - DefaultAzureCredential
against a real vault.

Key Vault names allow letters, digits and dashes only, so APP_SECRET_KEY is
stored as APP-SECRET-KEY.
"""
from __future__ import annotations

import os
import sys
import time
from collections.abc import MutableMapping
from typing import Any

# Set on the `web` service by compose as well as on the backend. web is a
# Next.js image that never reads the vault, so serving one of these moves only
# the backend: it starts expecting a token the frontend does not send, and every
# server-side render 401s. That happened once with Infisical. Never loaded,
# never seeded.
SHARED_WITH_WEB = frozenset(
    {
        "INTERNAL_API_TOKEN",
        "INTERNAL_JWT_SECRET",
        "INTERNAL_JWT_SECRET_PREVIOUS",
        "INTERNAL_AUTH",
        "APP_ENV",
    }
)


def secret_name(env_key: str) -> str:
    return env_key.replace("_", "-")


def env_key(name: str) -> str:
    return name.replace("-", "_").upper()


class _EmulatorCredential:
    """Floci validates no token in dev mode; a real vault never sees this one."""

    def get_token(self, *scopes: str, **kwargs: Any):
        from azure.core.credentials import AccessToken

        return AccessToken("emulator", int(time.time()) + 3600)

    def get_token_info(self, *scopes: str, **kwargs: Any):
        from azure.core.credentials import AccessTokenInfo

        return AccessTokenInfo("emulator", int(time.time()) + 3600)


def client(url: str, environ: MutableMapping[str, str] = os.environ):
    from azure.keyvault.secrets import SecretClient

    ca = environ.get("AZURE_EMULATOR_CA", "").strip()
    if not ca:
        from azure.identity import DefaultAzureCredential

        return SecretClient(url, DefaultAzureCredential())
    if environ.get("APP_ENV", "").strip().lower() == "production":
        # The emulator's terms - any token, any challenge - are a hole anywhere real.
        raise RuntimeError("AZURE_EMULATOR_CA is set with APP_ENV=production")
    return SecretClient(
        url,
        _EmulatorCredential(),
        connection_verify=ca,
        verify_challenge_resource=False,
    )


def load(environ: MutableMapping[str, str] = os.environ, *, vault: Any = None) -> list[str]:
    """Copy every enabled secret into `environ`. Returns the variable names set."""
    url = environ.get("KEY_VAULT_URL", "").strip()
    if not url:
        return []
    vault = vault or client(url, environ)
    loaded = []
    for props in vault.list_properties_of_secrets():
        key = env_key(props.name)
        if props.enabled is False or key in SHARED_WITH_WEB:
            continue
        value = vault.get_secret(props.name).value
        if value is not None:
            environ[key] = value
            loaded.append(key)
    return sorted(loaded)


def main(argv: list[str]) -> int:
    command = argv[argv.index("--") + 1 :] if "--" in argv else argv
    if not command:
        print("usage: python -m cbc.shared.keyvault -- <command> [args...]", file=sys.stderr)
        return 2
    url = os.environ.get("KEY_VAULT_URL", "")
    try:
        names = load()
        print(f"[entrypoint] {len(names)} secret(s) from Key Vault {url}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 - fail-open: the mounted .env still works
        print(
            f"[entrypoint] Key Vault {url} unavailable ({type(exc).__name__}: {exc}) - using .env",
            file=sys.stderr,
        )
    os.execvp(command[0], command)
    return 0  # unreachable: execvp replaces the process


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
