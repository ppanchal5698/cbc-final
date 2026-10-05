"""The typed-question adapter: validated answer, one retry, None, never a raise."""
from __future__ import annotations

import json
import subprocess
from typing import Literal

from pydantic import BaseModel

from cbc.shared import ai


class Handing(BaseModel):
    handing: Literal["LH", "RH", "LHR", "RHR", "none"]
    reason: str


QUESTION = ai.Question("read_door_handing", 1, "Read the swing.", Handing)


def scripted(*answers):
    calls = []

    def send(instructions, prompt, images, schema):
        calls.append(prompt)
        answer = answers[len(calls) - 1]
        if isinstance(answer, Exception):
            raise answer
        return answer

    send.calls = calls
    return send


def test_a_valid_answer_comes_back_typed():
    asked = ai.ask(QUESTION, "door 101", transport=scripted({"handing": "LH", "reason": "arc left"}))
    assert asked.answer == Handing(handing="LH", reason="arc left")


def test_an_invalid_answer_is_retried_once_with_the_error():
    send = scripted({"handing": "left"}, {"handing": "RH", "reason": "arc right"})
    asked = ai.ask(QUESTION, "door 101", transport=send)
    assert asked.answer.handing == "RH"
    assert "rejected" in send.calls[1]


def test_two_invalid_answers_give_none_not_a_raise():
    asked = ai.ask(QUESTION, "door 101", transport=scripted({"x": 1}, {"y": 2}))
    assert asked.answer is None and "schema" in asked.error


def test_an_unreachable_provider_gives_none():
    asked = ai.ask(QUESTION, "door 101", transport=scripted(ai.TransportError("offline")))
    assert asked.answer is None and asked.error == "offline"


def test_the_cache_answers_without_asking_and_expires_with_the_version(tmp_path):
    image = tmp_path / "swing.png"
    image.write_bytes(b"png")
    cache: dict = {}
    ai.ask(QUESTION, "door 101", images=[image], transport=scripted({"handing": "LH", "reason": "r"}), cache=cache)
    again = ai.ask(QUESTION, "door 101", images=[image], transport=scripted(), cache=cache)
    assert again.cached and again.answer.handing == "LH"
    bumped = ai.Question("read_door_handing", 2, "Read the swing.", Handing)
    assert ai.cache_key(bumped, "door 101", [image]) not in cache
    image.write_bytes(b"other page")
    assert ai.cache_key(QUESTION, "door 101", [image]) not in cache


def test_the_cli_gets_no_tools_but_read_and_its_structured_output_is_the_answer(monkeypatch, tmp_path):
    seen = {}

    def fake_run(argv, cwd, **kwargs):
        seen["argv"], seen["files"] = argv, sorted(p.name for p in __import__("pathlib").Path(cwd).iterdir())
        body = {"is_error": False, "structured_output": {"handing": "LHR", "reason": "r"}}
        return subprocess.CompletedProcess(argv, 0, json.dumps(body), "")

    monkeypatch.setattr(ai.subprocess, "run", fake_run)
    image = tmp_path / "crop.png"
    image.write_bytes(b"png")
    asked = ai.ask(QUESTION, "door 101", images=[image], transport=ai.cli_transport({}, claude_bin="claude"))
    assert asked.answer.handing == "LHR"
    argv = seen["argv"]
    assert argv[argv.index("--tools") + 1] == "Read"
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert "--strict-mcp-config" in argv
    assert seen["files"] == ["image_1.png"]  # the only thing it can read


def test_a_cli_error_is_a_transport_error_not_an_answer(monkeypatch):
    monkeypatch.setattr(ai.subprocess, "run", lambda argv, **k: subprocess.CompletedProcess(
        argv, 1, json.dumps({"is_error": True, "result": "You've hit your session limit"}), ""))
    asked = ai.ask(QUESTION, "door 101", transport=ai.cli_transport({}, claude_bin="claude"))
    assert asked.answer is None and "session limit" in asked.error


def test_the_api_transport_forces_the_answer_tool(monkeypatch):
    sent = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"content": [{"type": "tool_use", "name": "answer", "input": {"handing": "RHR", "reason": "r"}}]}

    def fake_post(url, headers, json, timeout):
        sent.update(json)
        return Response()

    monkeypatch.setattr(ai.httpx, "post", fake_post)
    asked = ai.ask(QUESTION, "door 101", transport=ai.api_transport({"ANTHROPIC_API_KEY": "k"}))
    assert asked.answer.handing == "RHR"
    assert sent["tool_choice"] == {"type": "tool", "name": "answer"}
    assert sent["tools"][0]["input_schema"] == Handing.model_json_schema()


def test_only_an_anthropic_key_uses_the_api():
    assert ai.transport_for("anthropic_api", {"ANTHROPIC_API_KEY": "k"}).__qualname__.startswith("api_transport")
    assert ai.transport_for("bedrock", {"ANTHROPIC_API_KEY": "k"}).__qualname__.startswith("cli_transport")
    assert ai.transport_for("anthropic_api", {}).__qualname__.startswith("cli_transport")
