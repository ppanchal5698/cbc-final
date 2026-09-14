"""Unit tests for MinerU parsing_config resolution and validation."""
from __future__ import annotations

import pytest

from cbc.modules.ops.api import parsing_config


def test_resolve_prefers_process_env(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("PARSER_BACKEND=pipeline\nPARSER_PROFILE=low\n", encoding="utf-8")
    monkeypatch.setenv("CBC_ENV_FILE", str(env_file))
    monkeypatch.setenv("PARSER_BACKEND", "vlm-engine")
    monkeypatch.delenv("PARSER_URL", raising=False)

    resolved, sources = parsing_config.resolve({"backend": "hybrid-engine", "profile": "medium"})
    assert resolved["backend"] == "vlm-engine"
    assert sources["backend"] == "env"


def test_resolve_dotenv_before_db(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "PARSER_BACKEND=pipeline\nPARSER_PROFILE=low\nPARSER_URL=http://mineru:8000\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CBC_ENV_FILE", str(env_file))
    monkeypatch.delenv("PARSER_BACKEND", raising=False)
    monkeypatch.delenv("PARSER_URL", raising=False)

    resolved, sources = parsing_config.resolve({"backend": "hybrid-engine", "url": "http://other"})
    assert resolved["backend"] == "pipeline"
    assert sources["backend"] == "dotenv"
    assert resolved["url"] == "http://mineru:8000"
    assert sources["url"] == "dotenv"


def test_resolve_prefer_config_beats_dotenv(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("PARSER_BACKEND=pipeline\n", encoding="utf-8")
    monkeypatch.setenv("CBC_ENV_FILE", str(env_file))
    monkeypatch.delenv("PARSER_BACKEND", raising=False)

    resolved, sources = parsing_config.resolve(
        {"backend": "hybrid-engine", "profile": "medium", "effort": "medium"},
        prefer_config=True,
    )
    assert resolved["backend"] == "hybrid-engine"
    assert sources["backend"] == "db"


def test_resolve_falls_back_to_profile_preset(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("CBC_ENV_FILE", str(env_file))
    for key in list(parsing_config.FIELDS.values()):
        monkeypatch.delenv(key, raising=False)

    resolved, sources = parsing_config.resolve({"profile": "high"})
    assert resolved["backend"] == "hybrid-engine"
    assert resolved["effort"] == "high"
    assert resolved["windowPages"] == 32
    assert resolved["imageAnalysis"] is True
    assert sources["backend"] == "profile"


def test_validate_rejects_bad_backend():
    problems = parsing_config.validate({"backend": "http-client", "profile": "low"})
    assert any("backend" in p for p in problems)


def test_validate_rejects_effort_without_hybrid():
    problems = parsing_config.validate(
        {"backend": "pipeline", "effort": "medium", "profile": "low"}
    )
    assert any("effort" in p for p in problems)


def test_validate_rejects_out_of_range_window():
    problems = parsing_config.validate({"windowPages": 0, "profile": "low", "backend": "pipeline"})
    assert any("windowPages" in p for p in problems)
    problems = parsing_config.validate(
        {"windowPages": 201, "profile": "low", "backend": "pipeline"}
    )
    assert any("windowPages" in p for p in problems)


def test_enabled_requires_url(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("CBC_ENV_FILE", str(env_file))
    for key in list(parsing_config.FIELDS.values()):
        monkeypatch.delenv(key, raising=False)

    resolved, _ = parsing_config.resolve({})
    assert parsing_config.enabled(resolved) is False
    resolved["url"] = "http://mineru:8000"
    assert parsing_config.enabled(resolved) is True
