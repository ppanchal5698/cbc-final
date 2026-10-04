"""parsing_config resolution and validation.

The precedence chain (process env → .env → saved document → default) is the part
worth guarding: an operator pinning a value in the environment must not be able
to have it silently overwritten from the Settings screen.
"""
from __future__ import annotations

from cbc.modules.ops.api import parsing_config


def _isolate(monkeypatch, tmp_path, contents: str = ""):
    env_file = tmp_path / ".env"
    env_file.write_text(contents, encoding="utf-8")
    monkeypatch.setenv("CBC_ENV_FILE", str(env_file))
    for key in parsing_config.FIELDS.values():
        monkeypatch.delenv(key, raising=False)


def test_resolve_prefers_process_env(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path, "PARSER_TIER=cost_effective\n")
    monkeypatch.setenv("PARSER_TIER", "agentic_plus")

    resolved, sources = parsing_config.resolve({"tier": "agentic"})
    assert resolved["tier"] == "agentic_plus"
    assert sources["tier"] == "env"
    assert parsing_config.public_config({"tier": "agentic"})["fields"]["tier"]["locked"] is True


def test_resolve_dotenv_before_db(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path, "PARSER_TIER=cost_effective\nPARSER_API_KEY=llx-from-file\n")

    resolved, sources = parsing_config.resolve({"tier": "agentic", "apiKey": "llx-from-db"})
    assert resolved["tier"] == "cost_effective"
    assert sources["tier"] == "dotenv"
    assert resolved["apiKey"] == "llx-from-file"


def test_resolve_prefer_config_beats_dotenv(monkeypatch, tmp_path):
    """The Settings Test button tries what is on screen, not what is saved."""
    _isolate(monkeypatch, tmp_path, "PARSER_TIER=cost_effective\n")

    resolved, sources = parsing_config.resolve({"tier": "agentic"}, prefer_config=True)
    assert resolved["tier"] == "agentic"
    assert sources["tier"] == "db"


def test_resolve_falls_back_to_defaults(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)

    resolved, sources = parsing_config.resolve({})
    assert resolved["tier"] == parsing_config.DEFAULT_TIER
    assert resolved["windowPages"] == 8
    assert resolved["windowTimeoutSeconds"] == 1800
    assert sources["tier"] == "default"


def test_validate_rejects_fast_tier_by_name():
    """`fast` is cheap and useless here: no granular boxes means no evidence."""
    problems = parsing_config.validate({"tier": "fast"})
    assert problems
    assert any("granular" in p for p in problems)


def test_validate_rejects_unknown_tier():
    problems = parsing_config.validate({"tier": "turbo"})
    assert any("tier" in p for p in problems)


def test_validate_accepts_every_supported_tier():
    for tier in parsing_config.TIERS:
        assert parsing_config.validate({"tier": tier}) == []


def test_validate_rejects_out_of_range_window():
    assert any("windowPages" in p for p in parsing_config.validate({"windowPages": 0}))
    assert any("windowPages" in p for p in parsing_config.validate({"windowPages": 201}))


def test_enabled_requires_an_api_key(monkeypatch, tmp_path):
    """The key is the on/off switch PARSER_URL used to be."""
    _isolate(monkeypatch, tmp_path)

    resolved, _ = parsing_config.resolve({})
    assert parsing_config.enabled(resolved) is False
    resolved["apiKey"] = "llx-abc"
    assert parsing_config.enabled(resolved) is True


def test_public_config_never_returns_the_key(monkeypatch, tmp_path):
    """This payload goes to the browser and into snapshots."""
    _isolate(monkeypatch, tmp_path)

    payload = parsing_config.public_config({"apiKey": "llx-super-secret-value"})
    assert payload["fields"]["apiKey"]["value"] == "set"
    assert "llx-super-secret-value" not in str(payload)
    assert payload["enabled"] is True
    assert payload["tiers"] == list(parsing_config.TIERS)

    blank = parsing_config.public_config({})
    assert blank["fields"]["apiKey"]["value"] == ""
    assert blank["enabled"] is False
