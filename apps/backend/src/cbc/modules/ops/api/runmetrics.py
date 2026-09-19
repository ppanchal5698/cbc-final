"""Parse a Claude recording into a `runMetrics` document.

The CLI already emits `modelUsage`, `total_cost_usd`, per-message `usage` and
tool calls in `--output-format stream-json`. Until this module existed only
`recording_warnings()` read that stream, and only for warning strings. Every
completed Claude job writes one document; failed runs still write.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cbc.shared.paths import repo_root
from cbc.modules.ops.infrastructure.collections import run_metrics as run_metrics_collection

ROOT = repo_root()

# CSI / colour codes wrapped around JSONL lines in a pty recording.
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\].*?(?:\x07|\x1b\\)")

PHASE_BY_JOB = {
    "extract_bid_set": "extraction",
    "rerun_extraction": "extraction",
    "ingest_addendum": "extraction",
    "match_and_price": "pricing",
    "build_proposal": "proposal",
    "run_full_pipeline": "pipeline",
    "ingest_pricebook": "ingest",
}

_MCP_TOOL = re.compile(r"^mcp__(.+?)__")

# Above this, a cache write is a whole context prefix rather than one turn's
# incremental append. The measured initial prefix is ~32k tokens; ordinary turns
# write a few hundred.
COLD_PREFIX_MIN_TOKENS = 8_000


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return _sha256_bytes(path.read_bytes())


def context_hashes(prompt: str | None = None) -> dict[str, Any]:
    """SHA-256 of the files a run actually followed. Recorded, never reused."""
    rules_dir = ROOT / ".claude" / "rules"
    rules_blob = b"".join(
        path.read_bytes()
        for path in sorted(rules_dir.glob("*.md"))
        if path.is_file()
    )
    agents = {
        path.stem: _sha256_file(path)
        for path in sorted((ROOT / ".claude" / "agents").glob("*.md"))
        if path.is_file()
    }
    skills: dict[str, str | None] = {}
    for skill_md in sorted((ROOT / ".claude" / "skills").glob("*/SKILL.md")):
        skills[skill_md.parent.name] = _sha256_file(skill_md)
    # The process flow used to be one file. It is a directory now - an index
    # plus one document per phase - so hash the set the way rules are hashed.
    flow_blob = b"".join(
        path.read_bytes()
        for path in sorted((ROOT / "docs" / "pipeline").glob("*.md"))
        if path.is_file()
    )
    return {
        "prompt": _sha256_text(prompt or ""),
        "claudeMd": _sha256_file(ROOT / "CLAUDE.md"),
        "processFlow": _sha256_bytes(flow_blob) if flow_blob else None,
        "rules": _sha256_bytes(rules_blob) if rules_blob else None,
        "agents": agents,
        "skills": skills,
    }


def parse_recording(source: str | Path) -> dict[str, Any]:
    """Strip ANSI, json.loads each line, take the last `type=result` event."""
    if isinstance(source, Path) or not str(source).lstrip().startswith("{"):
        text = Path(source).read_text(encoding="utf-8", errors="replace")
    else:
        text = source

    events: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = _ANSI.sub("", raw_line).replace("\r", "").strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type"):
            events.append(event)

    result: dict[str, Any] = {}
    for event in events:
        if event.get("type") == "result":
            result = event

    model_usage = result.get("modelUsage") or {}
    tokens = _tokens_from_usage(model_usage, events)
    tools = _tools_from_events(events)
    return {
        "sessionId": result.get("session_id"),
        "durationApiMs": result.get("duration_api_ms"),
        "totalCostUsd": result.get("total_cost_usd"),
        "modelUsage": model_usage,
        "tokens": tokens,
        "tools": tools["tools"],
        "mcp": tools["mcp"],
        "subagents": tools["subagents"],
        "startedAt": _first_timestamp(events),
        "finishedAt": result.get("timestamp") or _last_timestamp(events),
    }


def _first_timestamp(events: list[dict[str, Any]]) -> str | None:
    for event in events:
        if event.get("timestamp"):
            return event["timestamp"]
    return None


def _last_timestamp(events: list[dict[str, Any]]) -> str | None:
    for event in reversed(events):
        if event.get("timestamp"):
            return event["timestamp"]
    return None


def _tokens_from_usage(
    model_usage: dict[str, Any], events: list[dict[str, Any]]
) -> dict[str, Any]:
    primary: dict[str, Any] = {}
    best_cost = -1.0
    for payload in model_usage.values():
        if not isinstance(payload, dict):
            continue
        cost = float(payload.get("costUSD") or 0)
        if cost >= best_cost:
            best_cost = cost
            primary = payload

    # One usage record per assistant *message*, not per streamed fragment.
    #
    # stream-json re-emits the same assistant message as it streams, and every
    # fragment carries the same cumulative `usage`. Summing the fragments counted
    # this run's cache writes as 835,071 tokens against a `cacheCreate` total of
    # 241,256 - a figure larger than the thing it is a subset of, which is how the
    # bug shows itself.
    per_message: dict[str, int] = {}
    for index, event in enumerate(events):
        if event.get("type") != "assistant":
            continue
        message = event.get("message") or {}
        usage = message.get("usage") or {}
        created = int(usage.get("cache_creation_input_tokens") or 0)
        if not created:
            continue
        # An id-less event cannot be deduplicated; count it once on its own key.
        per_message[str(message.get("id") or f"_event{index}")] = created

    # A *cold prefix* write is a whole context being cached from scratch - the
    # ~32k-token system prompt, CLAUDE.md, rules and tool schemas that each new
    # subagent re-instantiates. The few-hundred-token writes on every ordinary
    # turn are incremental caching of that turn's own output and are not the
    # thing this metric exists to count.
    cold_writes = [tokens for tokens in per_message.values() if tokens >= COLD_PREFIX_MIN_TOKENS]

    cache_create = int(primary.get("cacheCreationInputTokens") or 0)
    cache_read = int(primary.get("cacheReadInputTokens") or 0)
    denom = cache_read + cache_create
    cache_hit_ratio = round(cache_read / denom, 4) if denom > 0 else None

    return {
        "input": int(primary.get("inputTokens") or 0),
        "output": int(primary.get("outputTokens") or 0),
        "thinking": int(primary.get("thinkingTokens") or 0),
        "cacheCreate": cache_create,
        "cacheRead": cache_read,
        "cacheHitRatio": cache_hit_ratio,
        "coldPrefixWrites": len(cold_writes),
        "coldPrefixTokens": sum(cold_writes),
        "largestSinglePrefixWrite": max(cold_writes, default=0),
    }


def _content_blocks(event: dict[str, Any]) -> list[dict[str, Any]]:
    message = event.get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def _carries_an_image(block: dict[str, Any]) -> bool:
    """True when a tool_result puts image bytes into the context."""
    content = block.get("content")
    if not isinstance(content, list):
        return False
    return any(
        isinstance(part, dict) and part.get("type") == "image" for part in content
    )


def _result_chars(block: dict[str, Any]) -> int:
    # The recorder keeps a result's head and an image's size, not its pixels, and
    # says how much it left out (`omitted_chars`); the result was that big all the same.
    omitted = int(block.get("omitted_chars") or 0)
    content = block.get("content")
    if isinstance(content, str):
        return len(content) + omitted
    if content is None:
        return omitted
    try:
        return len(json.dumps(content, default=str)) + omitted
    except (TypeError, ValueError):
        return len(str(content)) + omitted


def _percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(pct / 100 * len(ordered)) - 1))
    return ordered[index]


def _tools_from_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    by_name: Counter[str] = Counter()
    by_agent: Counter[str] = Counter()
    tool_names: dict[str, str] = {}
    result_chars: list[int] = []
    image_chars = 0
    tool_times: list[datetime] = []

    for event in events:
        kind = event.get("type")
        stamp = _parse_ts(event.get("timestamp"))
        if kind == "assistant":
            for block in _content_blocks(event):
                if block.get("type") != "tool_use":
                    continue
                name = str(block.get("name") or "")
                by_name[name] += 1
                if block.get("id"):
                    tool_names[str(block["id"])] = name
                if name == "Agent":
                    sub = (block.get("input") or {}).get("subagent_type")
                    if sub:
                        by_agent[str(sub)] += 1
                if stamp:
                    tool_times.append(stamp)
        elif kind == "user":
            for block in _content_blocks(event):
                if block.get("type") != "tool_result":
                    continue
                chars = _result_chars(block)
                result_chars.append(chars)
                # Classified by what came back, not by which tool was called.
                # `get_page_image` returns a *path* (~200 chars); the pixels reach
                # the context when the agent then calls `Read` on that path. Keyed
                # on the tool name this counted 1,084 chars of JSON paths and
                # missed the 2,054,388 chars of base64 that were the actual cost.
                if _carries_an_image(block):
                    image_chars += chars

    gaps = [
        (tool_times[i] - tool_times[i - 1]).total_seconds() * 1000
        for i in range(1, len(tool_times))
    ]
    invoked = sorted(
        {
            match.group(1)
            for name in by_name
            if (match := _MCP_TOOL.match(name))
        }
    )
    return {
        "tools": {
            "callCount": sum(by_name.values()),
            "byName": dict(by_name),
            "resultChars": {
                "total": sum(result_chars),
                "max": max(result_chars, default=0),
                "p95": _percentile(result_chars, 95),
            },
            "imageResultChars": image_chars,
            "meanInterCallGapMs": round(sum(gaps) / len(gaps)) if gaps else None,
        },
        "mcp": {
            "exposed": [],
            "invoked": invoked,
            "toolsExposed": 0,
            "toolsInvoked": sum(1 for name in by_name if name.startswith("mcp__")),
        },
        "subagents": {
            "streamCount": sum(by_agent.values()),
            "byType": dict(by_agent),
        },
    }


def _parse_ts(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _job_id_str(job: dict[str, Any]) -> str:
    return str(job.get("_id") or "")


def parse_recording_name(name: str) -> tuple[str, int]:
    """`(jobId, attempt)` from `{jobId}.log` or `{jobId}-attemptN.log`."""
    stem = Path(name).name
    if stem.endswith(".log"):
        stem = stem[:-4]
    if "-attempt" in stem:
        job_id, _, rest = stem.partition("-attempt")
        try:
            return job_id, max(int(rest), 1)
        except ValueError:
            return job_id, 1
    return stem, 1


def document_for(
    job: dict[str, Any],
    parsed: dict[str, Any],
    *,
    prompt: str | None = None,
    project: dict[str, Any] | None = None,
    provider: dict[str, Any] | None = None,
    outcome_status: str | None = None,
    error_code: str | None = None,
) -> dict[str, Any]:
    job_id = _job_id_str(job)
    attempt = max(int(job.get("attempts") or 1), 1)
    job_type = job.get("type") or "unknown"
    exposed: list[str] = []
    try:
        from cbc.modules.ops.api import toolsets

        exposed = list(toolsets.PROFILES.get(job_type, ()))
    except Exception:
        exposed = []
    mcp = dict(parsed.get("mcp") or {})
    mcp["exposed"] = exposed or mcp.get("invoked") or []
    mcp["toolsExposed"] = mcp.get("toolsExposed") or 0

    started = job.get("startedAt") or parsed.get("startedAt")
    finished = job.get("finishedAt") or parsed.get("finishedAt")
    if isinstance(started, datetime):
        started = started.astimezone(timezone.utc).isoformat()
    if isinstance(finished, datetime):
        finished = finished.astimezone(timezone.utc).isoformat()

    return {
        "_id": f"{job_id}:{attempt}",
        "jobId": job_id,
        "attempt": attempt,
        "projectId": str(job["projectId"]) if job.get("projectId") else None,
        "projectSlug": (project or {}).get("slug"),
        "jobType": job_type,
        "phase": PHASE_BY_JOB.get(job_type),
        "stragglerMerge": bool((job.get("payload") or {}).get("stragglerMerge")),
        "provider": provider or job.get("provider"),
        "sessionId": parsed.get("sessionId"),
        "startedAt": started,
        "finishedAt": finished,
        "durationApiMs": parsed.get("durationApiMs"),
        "tokens": parsed.get("tokens") or {},
        "modelUsage": parsed.get("modelUsage") or {},
        "totalCostUsd": parsed.get("totalCostUsd"),
        "tools": parsed.get("tools") or {},
        "mcp": mcp,
        "subagents": parsed.get("subagents") or {},
        "contextHashes": context_hashes(prompt),
        "outcome": {
            "status": outcome_status or job.get("status") or "unknown",
            "errorCode": error_code or job.get("errorCode"),
            "retryReason": None,
            "rerunScope": None,
            "validationFailures": [],
            "reviewFlagCount": 0,
            # Filled by `record` from the corrections this bid has drawn (FR-13).
            # It was a placeholder here from the day the collection was written,
            # and an unfilled one is the difference between a matcher that is
            # said to be improving and one that can be shown to be.
            "estimatorCorrections": None,
        },
    }


async def record(
    job: dict[str, Any],
    recording: Path | None,
    *,
    prompt: str | None = None,
    project: dict[str, Any] | None = None,
    provider: dict[str, Any] | None = None,
    outcome_status: str | None = None,
    error_code: str | None = None,
) -> dict[str, Any] | None:
    """Upsert one runMetrics document. Missing recordings still write hashes."""
    parsed: dict[str, Any] = {}
    if recording is not None and recording.exists():
        parsed = parse_recording(recording)
    document = document_for(
        job,
        parsed,
        prompt=prompt,
        project=project,
        provider=provider,
        outcome_status=outcome_status,
        error_code=error_code,
    )
    await run_metrics_collection().replace_one({"_id": document["_id"]}, document, upsert=True)
    return document


async def set_estimator_corrections(job: dict[str, Any], counts: dict[str, Any]) -> None:
    """Record how much of this bid the estimator corrected, and how much CBC knows.

    Takes the numbers rather than gathering them: `feedbackEvents` belongs to
    extraction, extraction already imports ops, and a metric is not a good enough
    reason to put a cycle in the module graph. The caller that owns the queue
    counts it and hands the result here.

    The point of the learning loop is that these numbers fall. Recording them on
    every pass is what turns "it gets smarter" from a claim into something an
    operator can read - and what would show it plateauing, which is the signal to
    reach for a better recall than string similarity.
    """
    job_id = str(job.get("_id") or "")
    if not job_id or not counts:
        return
    attempt = max(int(job.get("attempts") or 1), 1)  # same key document_for builds
    await run_metrics_collection().update_one(
        {"_id": f"{job_id}:{attempt}"},
        {"$set": {"outcome.estimatorCorrections": counts}},
    )
