"""B-06: parse Claude recordings into runMetrics documents."""
from __future__ import annotations

from pathlib import Path

from tests.shared import FIXTURES, ROOT

FIXTURES = FIXTURES / "recordings"


def test_parser_takes_last_result_and_strips_ansi() -> None:
    from cbc.modules.ops.api import runmetrics

    parsed = runmetrics.parse_recording(FIXTURES / "extract_bid_set.jsonl")
    assert parsed["totalCostUsd"] == 1.9990174
    assert parsed["durationApiMs"] == 818643
    assert parsed["sessionId"] == "e4af4a1a-3db4-4ce4-b7af-4f29feb479ba"
    sonnet = parsed["modelUsage"]["global.anthropic.claude-sonnet-4-5-20250929-v1:0"]
    assert sonnet["cacheReadInputTokens"] == 1520848
    assert parsed["tokens"]["cacheRead"] == 1520848
    assert parsed["tokens"]["cacheHitRatio"] is not None
    assert 0 <= parsed["tokens"]["cacheHitRatio"] <= 1
    assert "coldPrefixWrites" in parsed["tokens"]
    assert parsed["tools"]["callCount"] >= 1
    assert parsed["subagents"]["streamCount"] >= 1


def test_document_for_tags_straggler_merge() -> None:
    from cbc.modules.ops.api import runmetrics

    doc = runmetrics.document_for(
        {"_id": "abc", "type": "extract_bid_set", "payload": {"stragglerMerge": True}, "attempts": 1},
        {"tokens": {"cacheRead": 100, "cacheCreate": 50, "cacheHitRatio": 0.6667}},
    )
    assert doc["stragglerMerge"] is True
    assert doc["tokens"]["cacheHitRatio"] == 0.6667


def test_parser_second_known_total() -> None:
    from cbc.modules.ops.api import runmetrics

    parsed = runmetrics.parse_recording(FIXTURES / "match_and_price.jsonl")
    assert parsed["totalCostUsd"] == 1.2621052500000003
    assert parsed["durationApiMs"] == 551350
    assert parsed["sessionId"] == "2a49b18c-0dfa-48ee-8356-ee33d1116526"


def test_cold_prefix_tokens_cannot_exceed_the_cache_writes_they_are_part_of() -> None:
    """stream-json repeats each assistant message as it streams, and every
    fragment carries the same cumulative `usage`. Summing fragments reported
    835,071 cold-prefix tokens against a 241,256 cacheCreate total - a subset
    larger than its own set, which is the only signal the bug gave.
    """
    from cbc.modules.ops.api import runmetrics

    for name in ("extract_bid_set.jsonl", "match_and_price.jsonl"):
        tokens = runmetrics.parse_recording(FIXTURES / name)["tokens"]
        assert tokens["coldPrefixTokens"] <= tokens["cacheCreate"], name
        assert tokens["largestSinglePrefixWrite"] <= tokens["cacheCreate"], name


def test_image_bytes_are_counted_from_the_result_not_the_tool_name() -> None:
    """`get_page_image` returns a path; `Read` is what puts the pixels in context.

    Keyed on the tool name this counted 1,084 chars of JSON paths and missed the
    2,054,388 chars of base64 that were 89% of the run's tool-result bytes.
    """
    from cbc.modules.ops.api import runmetrics

    events = [
        {
            "type": "assistant",
            "message": {
                "id": "msg_1",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call_1",
                        "name": "Read",
                        "input": {"file_path": "sheet.png"},
                    }
                ],
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call_1",
                        "content": [
                            {
                                "type": "image",
                                "source": {"type": "base64", "data": "A" * 5000},
                            }
                        ],
                    }
                ]
            },
        },
    ]

    tools = runmetrics._tools_from_events(events)["tools"]
    assert tools["imageResultChars"] > 5000
    assert tools["imageResultChars"] == tools["resultChars"]["total"]


def test_context_hashes_cover_prompt_rules_agents_and_skills() -> None:
    from cbc.modules.ops.api import runmetrics

    first = runmetrics.context_hashes("hello")
    second = runmetrics.context_hashes("hello")
    other = runmetrics.context_hashes("goodbye")

    assert first["prompt"] == second["prompt"]
    assert first["prompt"] != other["prompt"]
    assert first["claudeMd"] and len(first["claudeMd"]) == 64
    assert first["processFlow"] and len(first["processFlow"]) == 64
    assert first["rules"] and len(first["rules"]) == 64
    assert "takeoff-engineer" in first["agents"]
    assert "extract-door-schedule" in first["skills"]


def test_document_id_is_job_and_attempt() -> None:
    from cbc.modules.ops.api import runmetrics

    parsed = runmetrics.parse_recording(FIXTURES / "extract_bid_set.jsonl")
    document = runmetrics.document_for(
        {"_id": "6a983a6a252290d4e1b0dc59", "attempts": 1, "type": "extract_bid_set"},
        parsed,
        prompt="phase 2",
        outcome_status="done",
    )
    assert document["_id"] == "6a983a6a252290d4e1b0dc59:1"
    assert document["jobType"] == "extract_bid_set"
    assert document["phase"] == "extraction"
    assert document["totalCostUsd"] == 1.9990174
    assert document["contextHashes"]["prompt"]
    assert document["outcome"]["status"] == "done"


def test_parse_recording_name_splits_retry_suffix() -> None:
    from cbc.modules.ops.api import runmetrics

    assert runmetrics.parse_recording_name("abc.log") == ("abc", 1)
    assert runmetrics.parse_recording_name("abc-attempt3.log") == ("abc", 3)


def test_timestamps_are_stored_as_dates_not_strings() -> None:
    """Mongo ranges String and Date in separate BSON type brackets.

    These were written with `.isoformat()`, so every
    `{"startedAt": {"$gte": <datetime>}}` matched nothing. That disabled both
    readers of this collection at once: `/api/ops/spend` reported zeros, and
    `cost_budget.spend_usd` summed to 0.0 - so WORKER_MAX_COST_USD_PER_DAY and
    WORKER_MAX_COST_USD_PER_PROJECT never fired. A spend cap that cannot fire on
    a pipeline being investigated for cost is worse than no cap, because the
    number on screen says it is watching.
    """
    from datetime import datetime, timezone

    from cbc.modules.ops.api import runmetrics

    moment = datetime(2026, 9, 21, 12, 30, tzinfo=timezone.utc)
    doc = runmetrics.document_for(
        {"_id": "abc", "type": "extract_bid_set", "attempts": 1,
         "startedAt": moment, "finishedAt": moment},
        {},
    )
    assert isinstance(doc["startedAt"], datetime), f"got {type(doc['startedAt'])}"
    assert isinstance(doc["finishedAt"], datetime)
    assert doc["startedAt"] == moment


def test_a_timestamp_from_the_recording_is_parsed_not_passed_through() -> None:
    """The job carries datetimes; the recording's own events carry strings."""
    from datetime import datetime, timezone

    from cbc.modules.ops.api import runmetrics

    doc = runmetrics.document_for(
        {"_id": "abc", "type": "extract_bid_set", "attempts": 1},
        {"startedAt": "2026-09-21T12:30:00Z", "finishedAt": "2026-09-21T12:45:00+00:00"},
    )
    assert doc["startedAt"] == datetime(2026, 9, 21, 12, 30, tzinfo=timezone.utc)
    assert doc["finishedAt"] == datetime(2026, 9, 21, 12, 45, tzinfo=timezone.utc)

    # Nothing usable is better than a string that will never match a range.
    junk = runmetrics.document_for(
        {"_id": "abc", "type": "extract_bid_set", "attempts": 1},
        {"startedAt": "not a time"},
    )
    assert junk["startedAt"] is None
