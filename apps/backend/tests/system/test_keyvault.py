"""Secrets load from Key Vault before the process starts, and never take the stack down."""
from __future__ import annotations

import socket
import ssl
import urllib.request
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

from cbc.shared import keyvault


class _Vault:
    def __init__(self, secrets: dict[str, str], disabled: frozenset[str] = frozenset()) -> None:
        self.secrets, self.disabled = secrets, disabled

    def list_properties_of_secrets(self):
        return [SimpleNamespace(name=n, enabled=n not in self.disabled) for n in self.secrets]

    def get_secret(self, name: str):
        return SimpleNamespace(value=self.secrets[name])


def test_secrets_become_environment_and_override_it() -> None:
    environ = {"KEY_VAULT_URL": "https://vault", "ANTHROPIC_API_KEY": "from-dotenv"}
    vault = _Vault({"ANTHROPIC-API-KEY": "from-vault", "PARSER-API-KEY": "p"})

    assert keyvault.load(environ, vault=vault) == ["ANTHROPIC_API_KEY", "PARSER_API_KEY"]
    assert environ["ANTHROPIC_API_KEY"] == "from-vault"


def test_disabled_and_web_shared_secrets_are_never_loaded() -> None:
    """Serving INTERNAL_JWT_SECRET to the backend alone breaks every page render."""
    environ = {"KEY_VAULT_URL": "https://vault", "INTERNAL_JWT_SECRET": "compose"}
    vault = _Vault({"INTERNAL-JWT-SECRET": "vault", "OLD-KEY": "x"}, disabled=frozenset({"OLD-KEY"}))

    assert keyvault.load(environ, vault=vault) == []
    assert environ["INTERNAL_JWT_SECRET"] == "compose"


def test_no_vault_configured_loads_nothing() -> None:
    assert keyvault.load({}, vault=_Vault({"A": "b"})) == []


def test_the_emulators_terms_are_refused_in_production() -> None:
    environ = {"AZURE_EMULATOR_CA": "/tmp/ca.pem", "APP_ENV": "production"}
    with pytest.raises(RuntimeError, match="production"):
        keyvault.client("https://vault", environ)


def test_an_unreachable_vault_still_starts_the_command(monkeypatch) -> None:
    """Fail-open: the mounted .env is the fallback, not an outage."""
    monkeypatch.setenv("KEY_VAULT_URL", "https://vault")
    monkeypatch.setattr(keyvault, "load", lambda: (_ for _ in ()).throw(OSError("down")))
    started: list[list[str]] = []
    monkeypatch.setattr(keyvault.os, "execvp", lambda file, args: started.append(args))

    keyvault.main(["--", "uvicorn", "app"])
    assert started == [["uvicorn", "app"]]


FLOCI_VAULT = "https://localhost:4577/devstoreaccount1-keyvault"


def test_a_secret_round_trips_through_the_local_emulator(tmp_path, monkeypatch) -> None:
    pytest.importorskip("azure.keyvault.secrets")
    host = urlparse(FLOCI_VAULT)
    try:
        socket.create_connection((host.hostname, host.port), timeout=1).close()
    except OSError:
        pytest.skip("Floci is not listening on localhost:4577")
    unverified = ssl.create_default_context()
    unverified.check_hostname, unverified.verify_mode = False, ssl.CERT_NONE
    ca = tmp_path / "floci.pem"
    with urllib.request.urlopen("https://localhost:4577/_floci/tls-cert", context=unverified) as cert:
        ca.write_bytes(cert.read())

    environ = {"KEY_VAULT_URL": FLOCI_VAULT, "AZURE_EMULATOR_CA": str(ca)}
    keyvault.client(FLOCI_VAULT, environ).set_secret("CBC-PYTEST-PROBE", "round-trip")

    assert "CBC_PYTEST_PROBE" in keyvault.load(environ)
    assert environ["CBC_PYTEST_PROBE"] == "round-trip"
