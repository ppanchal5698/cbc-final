"""Logs an aggregator can read without regexing sentences back into fields.

The worker called `basicConfig` with a human format; the API configured nothing
and inherited uvicorn's. So the two halves of one job logged in two shapes, and
`17:42:01 INFO  job build_proposal done - 3 artifacts` had to be parsed back into
the fields that were thrown away to write it.
"""
from __future__ import annotations

import json
import logging

import pytest

from cbc.shared import logs


@pytest.fixture(autouse=True)
def _restore_root_logging():
    root = logging.getLogger()
    saved, level = root.handlers[:], root.level
    yield
    root.handlers[:] = saved
    root.setLevel(level)


def _emit(capsys, monkeypatch, fmt: str, **context) -> str:
    monkeypatch.setenv("LOG_FORMAT", fmt)
    log = logs.configure("cbc.test")
    (logs.bind(log, **context) if context else log).info("job %s done", "build_proposal")
    return capsys.readouterr().out.strip()


def test_json_format_emits_one_object_per_line(capsys, monkeypatch) -> None:
    payload = json.loads(_emit(capsys, monkeypatch, "json"))
    assert payload["level"] == "INFO"
    assert payload["logger"] == "cbc.test"
    assert payload["message"] == "job build_proposal done"
    assert payload["ts"]


def test_bound_context_becomes_fields_not_message_text(capsys, monkeypatch) -> None:
    payload = json.loads(
        _emit(capsys, monkeypatch, "json", job_id="6512ab", project_code="DB-001")
    )
    assert payload["job_id"] == "6512ab"
    assert payload["project_code"] == "DB-001"
    assert "6512ab" not in payload["message"], "context belongs in a field"


def test_the_default_stays_human_readable(capsys, monkeypatch) -> None:
    """The common case is somebody watching `docker compose logs -f`."""
    line = _emit(capsys, monkeypatch, "")
    assert "job build_proposal done" in line
    assert not line.startswith("{")


def test_none_context_is_dropped_rather_than_logged_as_null(capsys, monkeypatch) -> None:
    payload = json.loads(_emit(capsys, monkeypatch, "json", job_id="x", project_id=None))
    assert payload["job_id"] == "x"
    assert "project_id" not in payload


def test_unserialisable_context_cannot_crash_the_log_call(capsys, monkeypatch) -> None:
    """An ObjectId or a datetime in the context must not take the process with it."""
    from datetime import datetime

    payload = json.loads(_emit(capsys, monkeypatch, "json", at=datetime(2026, 9, 1)))
    assert "2026-09-01" in payload["at"]


def test_configuring_twice_does_not_double_every_line(capsys, monkeypatch) -> None:
    monkeypatch.setenv("LOG_FORMAT", "json")
    logs.configure("cbc.test")
    log = logs.configure("cbc.test")
    log.info("once")
    assert len(capsys.readouterr().out.strip().splitlines()) == 1


def test_the_level_is_configurable(capsys, monkeypatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("LOG_FORMAT", "json")
    log = logs.configure("cbc.test")
    log.info("suppressed")
    log.warning("kept")
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["message"] == "kept"


def test_both_services_use_the_shared_setup() -> None:
    """Neither may go back to its own basicConfig."""
    from tests.shared import PKG

    # One worker composition root, one API composition root.
    entries = [
        PKG / "worker" / "main.py",
        PKG / "app" / "main.py",
    ]
    assert all(path.is_file() for path in entries), entries
    for path in entries:
        body = path.read_text(encoding="utf-8")
        assert "logs.configure(" in body, path
        assert "logging.basicConfig(" not in body, path
