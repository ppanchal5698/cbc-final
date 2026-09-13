"""Provider resolution, credential handling, and what must never leak.

The provider layer is where a wrong answer is expensive in two directions: get
the variable wrong and every job fails with an unexplained 401, get the handling
wrong and a credential ends up in a database, a log, or the audit trail.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from tests.shared import ROOT, opshub_client  # noqa: E402

TEST_DB = "cbc_opshub_test_provider"

from cbc.modules.ops.api import provider  # noqa: E402
from cbc.core import secrets  # noqa: E402
from cbc.persistence import names


@pytest.fixture(scope="module")
def client():
    with opshub_client(TEST_DB) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """No test may inherit a real credential from the developer's shell."""
    for variable in provider.MANAGED:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("APP_SECRET_KEY", "test-key-for-provider-tests")


# ── the variables themselves ────────────────────────────────────────────────


def test_each_mode_sets_the_variable_that_provider_actually_reads():
    """These are not interchangeable: the wrong one arrives in a header nobody reads."""
    env, _ = provider.build_env({"mode": provider.ANTHROPIC_API, "apiKey": "sk-ant-plain"})
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-plain"  # x-api-key
    assert "ANTHROPIC_AUTH_TOKEN" not in env

    env, _ = provider.build_env(
        {"mode": provider.GATEWAY, "baseUrl": "http://litellm:4000", "authToken": "sk-gw"}
    )
    assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-gw"  # Authorization: Bearer
    assert env["ANTHROPIC_BASE_URL"] == "http://litellm:4000"
    assert "ANTHROPIC_API_KEY" not in env

    env, _ = provider.build_env({"mode": provider.SUBSCRIPTION, "oauthToken": "sk-ant-oat-x"})
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat-x"


def test_bedrock_sets_its_flag_and_never_leaves_the_region_to_chance():
    """A container has no AWS profile, so an unset region lands somewhere arbitrary."""
    env, _ = provider.build_env({"mode": provider.BEDROCK})
    assert env["CLAUDE_CODE_USE_BEDROCK"] == "1"
    assert env["AWS_REGION"] == "us-east-1"
    assert env["ANTHROPIC_BEDROCK_REGION_PREFIX"] == "us"

    env, _ = provider.build_env({"mode": provider.BEDROCK, "awsRegion": "eu-west-1"})
    assert env["AWS_REGION"] == "eu-west-1"
    assert env["ANTHROPIC_BEDROCK_REGION_PREFIX"] == "eu"


def test_bedrock_rewrites_a_foundation_id_in_india_to_the_global_profile():
    """ap-south-1 has Claude only through Global CRIS, not apac. geo profiles."""
    env, _ = provider.build_env(
        {
            "mode": provider.BEDROCK,
            "awsRegion": "ap-south-1",
            "model": "anthropic.claude-sonnet-4-5-20250929-v1:0",
            "smallFastModel": "anthropic.claude-sonnet-4-5-20250929-v1:0",
        }
    )
    profile = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert env["ANTHROPIC_MODEL"] == profile
    assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == profile
    assert env["ANTHROPIC_BEDROCK_REGION_PREFIX"] == "global"
    assert env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == profile
    assert env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == profile
    assert env["CLAUDE_CODE_SUBAGENT_MODEL"] == profile


def test_bedrock_rewrites_a_foundation_id_in_us_east_to_the_us_profile():
    env, _ = provider.build_env(
        {
            "mode": provider.BEDROCK,
            "awsRegion": "us-east-1",
            "model": "anthropic.claude-sonnet-4-5-20250929-v1:0",
        }
    )
    profile = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert env["ANTHROPIC_MODEL"] == profile
    assert env["ANTHROPIC_BEDROCK_REGION_PREFIX"] == "us"
    assert env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == profile
    assert env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == profile
    assert env["CLAUDE_CODE_SUBAGENT_MODEL"] == profile
    assert "ANTHROPIC_DEFAULT_HAIKU_MODEL" not in env


def test_bedrock_leaves_prefixed_ids_and_aliases_alone():
    env, _ = provider.build_env(
        {
            "mode": provider.BEDROCK,
            "awsRegion": "ap-south-1",
            "model": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        }
    )
    assert env["ANTHROPIC_MODEL"] == "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert env["ANTHROPIC_BEDROCK_REGION_PREFIX"] == "global"

    env, _ = provider.build_env(
        {"mode": provider.BEDROCK, "awsRegion": "ap-south-1", "model": "sonnet"}
    )
    assert env["ANTHROPIC_MODEL"] == "sonnet"
    assert env["ANTHROPIC_BEDROCK_REGION_PREFIX"] == "global"
    assert "ANTHROPIC_DEFAULT_SONNET_MODEL" not in env
    assert "ANTHROPIC_DEFAULT_OPUS_MODEL" not in env
    assert "CLAUDE_CODE_SUBAGENT_MODEL" not in env


def test_bedrock_describe_warns_when_a_foundation_id_was_rewritten():
    described = provider.describe(
        {
            "mode": provider.BEDROCK,
            "awsRegion": "ap-south-1",
            "model": "anthropic.claude-sonnet-4-5-20250929-v1:0",
        }
    )
    assert described["model"] == "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert described["region"] == "ap-south-1"
    assert any("rewritten" in warning for warning in described["warnings"])


def test_ollama_mode_sets_anthropic_compatible_env():
    env, _ = provider.build_env(
        {
            "mode": provider.OLLAMA,
            "baseUrl": "http://host.docker.internal:11434",
            "model": "qwen2.5-coder:32b",
            "smallFastModel": "qwen2.5-coder:7b",
        }
    )
    assert env["ANTHROPIC_AUTH_TOKEN"] == "ollama"
    assert env["ANTHROPIC_API_KEY"] == ""
    assert env["ANTHROPIC_BASE_URL"] == "http://host.docker.internal:11434"
    assert env["ANTHROPIC_MODEL"] == "qwen2.5-coder:32b"
    assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "qwen2.5-coder:7b"
    assert env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "qwen2.5-coder:32b"
    assert env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "qwen2.5-coder:32b"
    assert env["CLAUDE_CODE_SUBAGENT_MODEL"] == "qwen2.5-coder:32b"
    assert env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
    assert env["CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT"] == "1"
    assert env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "65536"
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in env
    assert "CLAUDE_CODE_USE_BEDROCK" not in env


def test_ollama_describe_includes_warnings():
    described = provider.describe({"mode": provider.OLLAMA, "model": "gemma4:31b-cloud"})
    assert described["warnings"]
    assert any("Agent" in w or "Sonnet" in w for w in described["warnings"])


def test_ollama_defaults_haiku_and_subagents_to_main_model_when_unset():
    env, _ = provider.build_env(
        {"mode": provider.OLLAMA, "model": "gemma4:31b-cloud"},
    )
    assert env["ANTHROPIC_MODEL"] == "gemma4:31b-cloud"
    assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "gemma4:31b-cloud"
    assert env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "gemma4:31b-cloud"
    assert env["CLAUDE_CODE_SUBAGENT_MODEL"] == "gemma4:31b-cloud"


def test_bedrock_keeps_a_distinct_haiku_and_does_not_invent_one():
    env, _ = provider.build_env(
        {
            "mode": provider.BEDROCK,
            "awsRegion": "us-east-1",
            "model": "anthropic.claude-sonnet-4-5-20250929-v1:0",
            "smallFastModel": "anthropic.claude-haiku-4-5-20251001-v1:0",
        }
    )
    assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == (
        "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    )
    assert env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == (
        "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    )


def test_ollama_clears_stale_subscription_key(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat-stale")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-stale")

    env, _ = provider.build_env({"mode": provider.OLLAMA, "model": "glm-5:cloud"})

    assert "CLAUDE_CODE_OAUTH_TOKEN" not in env
    assert env["ANTHROPIC_API_KEY"] == ""
    assert env["ANTHROPIC_AUTH_TOKEN"] == "ollama"


def test_ollama_defaults_base_url_from_ollama_base_url_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")

    env, _ = provider.build_env({"mode": provider.OLLAMA, "model": "qwen3.5"})

    assert env["ANTHROPIC_BASE_URL"] == "http://host.docker.internal:11434"












def test_switching_provider_clears_the_previous_one(monkeypatch):
    """A stale key left in the environment would silently outrank the new choice."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")  # present but empty
    env, _ = provider.build_env({"mode": provider.BEDROCK, "awsRegion": "us-east-2"})

    assert "ANTHROPIC_API_KEY" not in env
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in env


def test_unmanaged_environment_is_passed_through(monkeypatch):
    """The subprocess still needs PATH, HOME and the rest of its environment."""
    monkeypatch.setenv("CLAUDE_BIN", "/usr/local/bin/claude")
    env, _ = provider.build_env({"mode": provider.SUBSCRIPTION})
    assert env["CLAUDE_BIN"] == "/usr/local/bin/claude"
    assert "PATH" in env


def test_database_credentials_are_withheld_from_the_subprocess(monkeypatch):
    """`MONGODB_URI` authenticates as root@admin and pymongo is in the image.

    Handing it to Claude Code would put a single Bash call past the catalog
    server's read-only assertion, which governs its tools and not its
    credentials. The catalog server is given a read-only string of its own
    through the MCP config instead (cbc_core/toolsets.py).
    """
    monkeypatch.setenv("MONGODB_URI", "mongodb://root:secret@mongo/db")
    monkeypatch.setenv("MONGODB_READONLY_PASSWORD", "also-secret")

    env, _ = provider.build_env({"mode": provider.SUBSCRIPTION})

    assert "MONGODB_URI" not in env
    assert "MONGODB_READONLY_PASSWORD" not in env


# ── precedence ──────────────────────────────────────────────────────────────


def test_environment_beats_the_database_and_says_so(monkeypatch):
    """On Fargate the credential comes from Secrets Manager.

    A value typed into the settings screen must not quietly replace it, and the
    screen has to be able to show the estimator why their edit will not apply.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-environment")

    config = {"mode": provider.ANTHROPIC_API, "apiKey": secrets.encrypt("sk-ant-from-database")}
    env, sources = provider.build_env(config)

    assert env["ANTHROPIC_API_KEY"] == "sk-ant-from-environment"
    assert sources["apiKey"] == "env"
    assert provider.public_config(config)["fields"]["apiKey"]["locked"] is True


def test_the_database_is_used_when_the_environment_is_silent():
    config = {"mode": provider.ANTHROPIC_API, "apiKey": secrets.encrypt("sk-ant-stored")}
    env, sources = provider.build_env(config)

    assert env["ANTHROPIC_API_KEY"] == "sk-ant-stored"
    assert sources["apiKey"] == "db"
    assert provider.public_config(config)["fields"]["apiKey"]["locked"] is False


# ── secrets ─────────────────────────────────────────────────────────────────


def test_a_credential_round_trips_but_is_not_stored_in_the_clear():
    stored = secrets.encrypt("sk-ant-api03-secret-value")
    assert stored.startswith("enc:")
    assert "sk-ant-api03-secret-value" not in stored
    assert secrets.decrypt(stored) == "sk-ant-api03-secret-value"


def test_a_credential_encrypted_under_a_lost_key_reads_as_unconfigured(monkeypatch):
    """Changing APP_SECRET_KEY must not stop the settings screen from loading."""
    stored = secrets.encrypt("sk-ant-old-key")
    monkeypatch.setenv("APP_SECRET_KEY", "a-completely-different-key")

    assert secrets.decrypt(stored) is None
    assert secrets.mask(stored) is None


def test_masking_shows_enough_to_recognise_and_not_enough_to_use():
    masked = secrets.mask(secrets.encrypt("sk-ant-api03-abcdefghijklmnop"))
    assert masked.startswith("sk-a") and masked.endswith("mnop")
    assert "api03-abcdefghij" not in masked


@pytest.mark.parametrize(
    "leaked",
    [
        "sk-ant-api03-abcdefghijklmnopqrstuv",
        "sk-or-v1-abcdefghijklmnopqrstuvwxyz",
        "nvapi-abcdefghijklmnopqrstuvwxyz",
        "AKIAIOSFODNN7EXAMPLE",
    ],
)
def test_recognisable_credentials_are_stripped_from_captured_output(leaked):
    """worker/main.py stores 8000 characters of this on every job."""
    cleaned = secrets.redact(f"error: request failed with key {leaked} at line 3")
    assert leaked not in cleaned
    assert "[redacted]" in cleaned


def test_an_unrecognisable_gateway_token_is_stripped_because_it_was_passed_in():
    """A bearer token can be any string, so pattern matching alone is not enough."""
    token = "totally-arbitrary-gateway-credential"
    cleaned = secrets.redact(f"401 rejected {token}", [token])
    assert token not in cleaned


def test_redaction_leaves_a_short_value_alone():
    """Redacting 'abc' would blank out ordinary prose across the whole log."""
    assert secrets.redact("failed at step abc", ["abc"]) == "failed at step abc"


# ── the endpoints ───────────────────────────────────────────────────────────


def test_settings_start_from_a_working_default(client):
    body = client.get("/api/settings/claude").json()
    assert body["mode"] == provider.SUBSCRIPTION
    assert set(body["modes"]) == set(provider.MODES)


def test_saving_a_credential_returns_it_masked_and_never_in_the_clear(client):
    response = client.put(
        "/api/settings/claude",
        json={"mode": "gateway", "baseUrl": "http://litellm:4000", "authToken": "sk-gw-secret"},
    )
    assert response.status_code == 200

    body = response.json()
    assert body["mode"] == "gateway"
    assert "sk-gw-secret" not in response.text
    assert body["fields"]["authToken"]["configured"] is True
    assert body["fields"]["baseUrl"]["value"] == "http://litellm:4000"


def test_saving_bedrock_settings_round_trips(client):
    """The stored model stays as typed; rewrite happens at spawn, not on save."""
    response = client.put(
        "/api/settings/claude",
        json={
            "mode": "bedrock",
            "awsRegion": "ap-south-1",
            "bedrockApiKey": "ABSK-test-bedrock-key-valueWT0=",
            "model": "anthropic.claude-sonnet-4-5-20250929-v1:0",
            "smallFastModel": "anthropic.claude-sonnet-4-5-20250929-v1:0",
        },
    )
    assert response.status_code == 200

    body = response.json()
    assert body["mode"] == "bedrock"
    assert "ABSK-test-bedrock-key-valueWT0=" not in response.text
    assert body["fields"]["bedrockApiKey"]["configured"] is True
    assert body["fields"]["awsRegion"]["value"] == "ap-south-1"
    assert body["fields"]["model"]["value"] == "anthropic.claude-sonnet-4-5-20250929-v1:0"

    from pymongo import MongoClient

    from cbc.shared.config import settings as app_settings

    raw = MongoClient(app_settings.mongodb_uri)
    try:
        stored = raw[TEST_DB]["settings"].find_one({"_id": "claude"})
    finally:
        raw.close()

    assert secrets.decrypt(stored["bedrockApiKey"]) == "ABSK-test-bedrock-key-valueWT0="
    assert stored["model"] == "anthropic.claude-sonnet-4-5-20250929-v1:0"

    from cbc.shared import envfile

    on_disk = envfile.read()
    assert on_disk["AWS_BEARER_TOKEN_BEDROCK"] == "ABSK-test-bedrock-key-valueWT0="
    assert on_disk["AWS_REGION"] == "ap-south-1"
    assert on_disk["CLAUDE_CODE_USE_BEDROCK"] == "1"
    assert on_disk["ANTHROPIC_MODEL"] == "anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert body["fields"]["bedrockApiKey"]["locked"] is False


def test_dotenv_beats_mongo_and_does_not_lock_the_field(tmp_path, monkeypatch):
    from cbc.shared import envfile

    envfile.upsert({"AWS_BEARER_TOKEN_BEDROCK": "ABSK-from-dotenv-fileWT0=", "AWS_REGION": "ap-south-1"})
    env, sources = provider.build_env({"mode": provider.BEDROCK, "bedrockApiKey": secrets.encrypt("ABSK-from-mongoWT0=")})
    assert env["AWS_BEARER_TOKEN_BEDROCK"] == "ABSK-from-dotenv-fileWT0="
    assert sources["bedrockApiKey"] == "dotenv"
    assert provider.public_config({"mode": provider.BEDROCK})["fields"]["bedrockApiKey"]["locked"] is False


def test_process_env_still_beats_the_dotenv_file(monkeypatch):
    from cbc.shared import envfile

    envfile.upsert({"AWS_BEARER_TOKEN_BEDROCK": "ABSK-from-dotenv-fileWT0="})
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "ABSK-from-process-envWT0=")
    env, sources = provider.build_env({"mode": provider.BEDROCK})
    assert env["AWS_BEARER_TOKEN_BEDROCK"] == "ABSK-from-process-envWT0="
    assert sources["bedrockApiKey"] == "env"
    assert provider.public_config({"mode": provider.BEDROCK})["fields"]["bedrockApiKey"]["locked"] is True


def test_envfile_upsert_preserves_unrelated_keys_and_comments(tmp_path, monkeypatch):
    from cbc.shared import envfile

    target = tmp_path / ".env"
    target.write_text("# keep me\nMONGODB_DB=cbc_opshub\nAWS_REGION=us-east-1\n", encoding="utf-8")
    monkeypatch.setenv("CBC_ENV_FILE", str(target))
    envfile.upsert({"AWS_BEARER_TOKEN_BEDROCK": "ABSK-secretWT0=", "AWS_REGION": "ap-south-1"})
    text = target.read_text(encoding="utf-8")
    assert "# keep me" in text
    assert "MONGODB_DB=cbc_opshub" in text
    assert "AWS_REGION=ap-south-1" in text
    assert "us-east-1" not in text
    assert "ABSK-secretWT0=" in text


def test_envfile_upsert_falls_back_when_replace_is_busy(tmp_path, monkeypatch):
    """Docker Desktop single-file bind mounts reject os.replace with EBUSY."""
    from cbc.shared import envfile

    target = tmp_path / ".env"
    target.write_text("FOO=1\n", encoding="utf-8")
    monkeypatch.setenv("CBC_ENV_FILE", str(target))

    real_replace = os.replace

    def busy_replace(src, dst):
        if Path(dst) == target:
            raise OSError(16, "Device or resource busy")
        return real_replace(src, dst)

    monkeypatch.setattr(envfile.os, "replace", busy_replace)
    assert envfile.upsert({"FOO": "2", "BAR": "x"}) is True
    text = target.read_text(encoding="utf-8")
    assert "FOO=2" in text
    assert "BAR=x" in text


def test_saving_ollama_settings_round_trips(client):
    response = client.put(
        "/api/settings/claude",
        json={
            "mode": "ollama",
            "baseUrl": "http://host.docker.internal:11434",
            "model": "qwen2.5-coder:32b",
            "smallFastModel": "qwen2.5-coder:7b",
        },
    )
    assert response.status_code == 200

    body = response.json()
    assert body["mode"] == "ollama"
    assert body["fields"]["baseUrl"]["value"] == "http://host.docker.internal:11434"
    assert body["fields"]["model"]["value"] == "qwen2.5-coder:32b"
    assert body["fields"]["smallFastModel"]["value"] == "qwen2.5-coder:7b"
    assert "ollama" in body["modes"]





def test_a_masked_value_sent_back_unedited_keeps_the_stored_credential(client):
    """The screen renders the mask; saving an unrelated field must not destroy the key.

    This asserted only that *something* was still configured, which the mask
    itself satisfied - so it passed while Save was quietly overwriting the real
    credential with `sk-a********p-me`. It now checks the actual stored value.
    """
    secret = "sk-ant-api03-keep-me-intact-abcdef"
    client.put(
        "/api/settings/claude",
        json={"mode": "anthropic_api", "apiKey": secret, "model": "sonnet"},
    )
    masked = client.get("/api/settings/claude").json()["fields"]["apiKey"]["value"]

    client.put(
        "/api/settings/claude",
        json={"mode": "anthropic_api", "apiKey": masked, "model": "opus"},
    )

    after = client.get("/api/settings/claude").json()
    assert after["fields"]["model"]["value"] == "opus"

    # The credential itself, not merely "configured" - which a mask satisfies too.
    from pymongo import MongoClient

    from cbc.shared.config import settings as app_settings

    raw = MongoClient(app_settings.mongodb_uri)
    try:
        stored = raw[TEST_DB]["settings"].find_one({"_id": "claude"})
    finally:
        raw.close()

    assert secrets.decrypt(stored["apiKey"]) == secret
    assert "****" not in secrets.decrypt(stored["apiKey"])


def test_saving_settings_records_the_change_without_the_values(client):
    """The trail has to show that a credential changed, and never what it became."""
    from pymongo import MongoClient

    from cbc.shared.config import settings as app_settings

    client.put(
        "/api/settings/claude",
        json={"mode": "anthropic_api", "apiKey": "sk-ant-must-not-be-audited"},
    )

    raw = MongoClient(app_settings.mongodb_uri)
    try:
        entries = list(
            raw[TEST_DB][names.AUDIT_LOGS].find({"action": "settings.claude.update"})
        )
    finally:
        raw.close()

    assert entries, "the change itself must be recorded"
    assert "apiKey" in entries[-1]["after"]["changed"]
    assert "sk-ant-must-not-be-audited" not in str(entries)
