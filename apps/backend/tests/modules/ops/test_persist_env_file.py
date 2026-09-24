"""Saving settings must not wipe values the form did not send.

This cost a real API key. The Settings screen omits `apiKey` when it was not
retyped - deliberately, so a masked placeholder cannot be posted over a real
secret - and `persist_env_file` read that absence as "clear it", writing
`PARSER_API_KEY=""`. Parsing silently switched off.

`envfile.upsert` deletes a key given None, so the same mistake on the other
fields removes them from `.env` entirely rather than resetting them to a default.
"""
from __future__ import annotations

import os

from cbc.modules.ops.api import parsing_config


def _env(tmp_path, monkeypatch, body: str):
    target = tmp_path / ".env"
    target.write_text(body, encoding="utf-8")
    monkeypatch.setenv("CBC_ENV_FILE", str(target))
    return target


def test_a_field_the_form_omitted_is_left_alone(tmp_path, monkeypatch):
    target = _env(
        tmp_path, monkeypatch,
        "PARSER_API_KEY=llx-real-secret\nPARSER_TIER=agentic\nUNRELATED=keep-me\n",
    )

    # Exactly what the Settings screen posts when only the tier was touched.
    parsing_config.persist_env_file({"tier": "agentic_plus"})

    body = target.read_text(encoding="utf-8")
    assert "PARSER_API_KEY=llx-real-secret" in body, "an untouched key was overwritten"
    assert "PARSER_TIER=agentic_plus" in body
    assert "UNRELATED=keep-me" in body


def test_an_omitted_field_is_never_deleted(tmp_path, monkeypatch):
    """upsert removes a key given None, so absent must not become None."""
    target = _env(
        tmp_path, monkeypatch,
        "PARSER_API_KEY=llx-real-secret\nPARSER_WINDOW_PAGES=16\n",
    )

    parsing_config.persist_env_file({"lang": "en"})

    body = target.read_text(encoding="utf-8")
    assert "PARSER_API_KEY=" in body, "key line was removed entirely"
    assert "PARSER_WINDOW_PAGES=16" in body
    assert "PARSER_LANG=en" in body


def test_an_explicit_empty_key_still_turns_parsing_off(tmp_path, monkeypatch):
    """Clearing the field on purpose is a real instruction and must work."""
    target = _env(tmp_path, monkeypatch, "PARSER_API_KEY=llx-real-secret\n")

    parsing_config.persist_env_file({"apiKey": ""})

    body = target.read_text(encoding="utf-8")
    assert "llx-real-secret" not in body
    assert "PARSER_API_KEY" in body


def test_values_round_trip_through_resolve(tmp_path, monkeypatch):
    target = _env(tmp_path, monkeypatch, "")
    for key in parsing_config.FIELDS.values():
        monkeypatch.delenv(key, raising=False)

    parsing_config.persist_env_file(
        {"apiKey": "llx-abc", "tier": "agentic", "windowConcurrency": 6}
    )
    resolved, sources = parsing_config.resolve({})

    assert resolved["apiKey"] == "llx-abc"
    assert resolved["tier"] == "agentic"
    assert resolved["windowConcurrency"] == 6
    assert sources["tier"] == "dotenv"
    assert target.read_text(encoding="utf-8")


def test_saving_a_field_does_not_lock_it_against_the_next_save(tmp_path, monkeypatch):
    """A value this screen wrote must not come back as an operator pin.

    `envfile.apply_to_environ` copies `.env` into `os.environ` at process start,
    and `resolve` reports process env as `env` - which locks the field in the UI
    and makes the PUT handler ignore what was typed. The parsing variables were
    not in the skip set, so saving a tier and restarting left the field greyed
    out for good, with later saves returning 200 and changing nothing.
    """
    from cbc.shared import envfile

    target = _env(tmp_path, monkeypatch, "")
    for key in parsing_config.FIELDS.values():
        monkeypatch.delenv(key, raising=False)

    parsing_config.persist_env_file({"tier": "agentic", "windowPages": 8})
    envfile.apply_to_environ(skip=parsing_config.MANAGED)

    assert "PARSER_TIER" not in os.environ, (
        "a tier this screen saved came back as a process pin; the field is now "
        "locked and further saves are silently discarded"
    )
    resolved, sources = parsing_config.resolve({"tier": "agentic"})
    assert sources["tier"] != "env"
    assert target.read_text(encoding="utf-8")


def test_a_real_process_pin_still_wins(tmp_path, monkeypatch):
    """Compose or `infisical run` setting it before Python starts is a real pin."""
    _env(tmp_path, monkeypatch, "PARSER_TIER=agentic\n")
    monkeypatch.setenv("PARSER_TIER", "agentic_plus")

    resolved, sources = parsing_config.resolve(None)
    assert resolved["tier"] == "agentic_plus"
    assert sources["tier"] == "env"
