"""Data-integrity and guardrail checks that need no database.

These cover the failures that only show up under concurrency, on a re-run, or on
a value that was already stored - the kind local development never produces.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from cbc.shared.config import settings
from tests.shared import ROOT

# â”€â”€ sync: identity keys must survive a re-run â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_repeated_marks_get_their_own_stable_keys() -> None:
    """A schedule really can list the same mark twice.

    Keying both on `mark:05` made each run insert two fresh rows and orphan the
    previous pair, because the lookup built before the loop only held one of them.
    """
    from cbc.modules.extraction.domain.schedule import _identity
    from cbc.shared.pass_files import distinct_keys as _distinct_keys

    openings = [{"mark": "01"}, {"mark": "05"}, {"mark": "05"}, {"mark": "07"}]
    keys = _distinct_keys(openings, _identity)

    assert keys == ["mark:01", "mark:05", "mark:05#2", "mark:07"]
    assert len(set(keys)) == len(keys), "keys collide within one payload"
    # Stable: the same schedule read again produces the same keys.
    assert _distinct_keys(openings, _identity) == keys


def test_priced_lines_key_on_content_not_position() -> None:
    """Re-ordering a re-priced quote must not duplicate every line."""
    from cbc.modules.quoting.api.priced_lines import _content_key
    from cbc.shared.pass_files import distinct_keys as _distinct_keys

    first = [
        {"part_number": "150CX18", "description": "Hinge", "division": "08 71 00"},
        {"part_number": "B-2888", "description": "Dispenser", "division": "10 28 00"},
    ]
    reordered = [first[1], first[0]]

    assert set(_distinct_keys(first, _content_key)) == set(
        _distinct_keys(reordered, _content_key)
    )


def test_an_explicit_line_id_wins() -> None:
    from cbc.modules.quoting.api.priced_lines import _content_key

    assert _content_key({"line_id": "L-7", "part_number": "X"}) == "L-7"


# â”€â”€ pricing: one bad line must not take the screen down â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_a_negative_cost_reports_unpriced_instead_of_raising() -> None:
    """`_recompute` walks every line on the bid.

    A single stored -45 used to raise out of the loop and 400 the quote and
    proposal screens, leaving no UI to correct it from.
    """
    from cbc.modules.pricing.api import pricing

    priced = pricing.price_line(cost=-45.0, margin=0.27, qty=1, division="08 71 00")

    assert priced["priced"] is False
    assert priced["sell"] is None and priced["extended"] is None
    assert "negative" in priced["error"]


def test_an_ordinary_line_still_prices() -> None:
    from cbc.modules.pricing.api import pricing

    priced = pricing.price_line(cost=74.33, margin=0.27, qty=3, division="08 71 00")
    assert priced["priced"] is True
    assert priced["sell"] == 101.82
    # 305.47, not 305.46: the extension is rounded once, from the unrounded
    # unit price. See test_the_extension_is_rounded_once_not_twice.
    assert priced["extended"] == 305.47


def test_quote_line_schema_rejects_a_negative_cost() -> None:
    from pydantic import ValidationError

    from cbc.modules.quoting.domain.quotes import QuoteLineUpdate

    with pytest.raises(ValidationError):
        QuoteLineUpdate(cost=-45)
    with pytest.raises(ValidationError):
        QuoteLineUpdate(qty=-1)
    assert QuoteLineUpdate(cost=45).cost == 45


def test_a_bad_cost_from_a_pipeline_run_is_flagged_not_stored() -> None:
    """The schema bounds what an estimator types; a run writes straight to Mongo."""
    from cbc.modules.quoting.api.priced_lines import _sane_cost

    cost, flags = _sane_cost({"cost": -45})
    assert cost is None and "negative cost" in flags[0]

    cost, flags = _sane_cost({"cost": "n/a"})
    assert cost is None and "unreadable cost" in flags[0]

    # An honest unpriced line stays unpriced, without inventing a flag.
    assert _sane_cost({"cost": None}) == (None, [])
    # And a good one is untouched.
    assert _sane_cost({"cost": 74.33, "flags": ["low_confidence"]}) == (74.33, ["low_confidence"])


# â”€â”€ the exclusive-job policy and its index must agree â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_pricebook_ingest_is_not_an_exclusive_job() -> None:
    """It carries no project, so every one of them shares the key (null, type).

    Including it made the second price-book upload of the day silently return the
    first one's job instead of being queued.
    """
    from cbc.schemas.common import EXCLUSIVE_JOB_TYPES
    from cbc.modules.ops.api.jobs import EXCLUSIVE

    assert "ingest_pricebook" not in EXCLUSIVE_JOB_TYPES
    assert EXCLUSIVE == set(EXCLUSIVE_JOB_TYPES)


def test_exclusive_active_job_index_is_one_per_project() -> None:
    """Two pipeline types on one bid must not both be active at once."""
    import inspect

    from cbc.modules.ops.infrastructure import collections

    source = inspect.getsource(collections.ensure_indexes)
    assert '"exclusive_active_job"' in source
    assert '("projectId", ASCENDING)]' in source
    assert '("projectId", ASCENDING), ("type", ASCENDING)' not in source


# â”€â”€ the worker knows which failures are worth retrying â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_a_missing_cli_is_not_retried(monkeypatch) -> None:
    from cbc.core import claude_cli as runner

    monkeypatch.setattr(runner, "resolve_binary", lambda: None)
    result = runner.run_claude("hello")

    assert result.ok is False
    assert result.permanent is True, "a missing CLI is the same on the third attempt"


def test_an_authentication_failure_is_not_retried() -> None:
    """The CLI exits 0 on an auth failure, so only the message identifies it."""
    from cbc.core import claude_cli as runner

    result = runner._interpret("Invalid API key", "", 0, timeout=90, redact_values=None)

    assert result.ok is False
    assert result.permanent is True


def test_an_ordinary_failure_is_still_retried() -> None:
    from cbc.core import claude_cli as runner

    result = runner._interpret("", "transient network blip", 1, timeout=90, redact_values=None)

    assert result.ok is False
    assert result.permanent is False


def test_a_bedrock_foundation_id_rejection_is_not_retried() -> None:
    from cbc.core import claude_cli as runner

    result = runner._interpret(
        "",
        "ValidationException: Invocation of model ID with on-demand throughput isn't supported. "
        "Retry with an inference profile.",
        1,
        timeout=90,
        redact_values=None,
    )

    assert result.ok is False
    assert result.permanent is True
    assert result.error_code == "bedrock_model_id"
    assert "inference-profile" in result.error


def test_a_bedrock_auth_refusal_is_not_retried() -> None:
    from cbc.core import claude_cli as runner

    result = runner._interpret(
        "",
        '403 {"Message":"Authorization header is missing"}',
        1,
        timeout=90,
        redact_values=None,
    )

    assert result.ok is False
    assert result.permanent is True
    assert result.error_code == "bedrock_auth"
    assert "AWS_BEARER_TOKEN_BEDROCK" in result.error


# â”€â”€ the file-safety hook sees Write and Edit, not only Bash â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _run_guard(payload: dict, project_root: str | None = None) -> subprocess.CompletedProcess:
    """Run the hook the way Claude Code runs it, with CLAUDE_PROJECT_DIR set.

    The guard protects *this project's* reference data and guardrails, resolved
    against that variable. It used to match any path segment called ".claude" or
    "pricebooks", which meant it also blocked writes to the user's own ~/.claude on
    the host - files that have nothing to do with this repository.
    """
    env = dict(os.environ, CLAUDE_PROJECT_DIR=project_root or str(ROOT))
    return subprocess.run(
        [sys.executable, str(ROOT / ".claude" / "hooks" / "pre_delete_guard.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        # The hook resolves a relative path against the process cwd, and Claude
        # Code runs it from the project dir. The archived suite ran from the repo
        # root, so it never had to say so; under apps/backend it must.
        cwd=ROOT,
    )


@pytest.mark.parametrize(
    "path",
    [
        "pricebooks/hager_price_book_18.pdf",
        "reference-library/margins/margin_framework.json",
        ".claude/hooks/pre_send_quote.py",
        ".claude/settings.json",
    ],
)
def test_write_to_protected_data_is_blocked(path: str) -> None:
    result = _run_guard({"tool_name": "Write", "tool_input": {"file_path": path}})
    assert result.returncode == 2, result.stdout
    assert "BLOCKED" in result.stderr


@pytest.mark.parametrize(
    "path", ["/app/pricebooks/index.json", "/app/.claude/settings.json"]
)
def test_the_container_layout_is_protected_too(path: str) -> None:
    """Same rule, resolved against the container's project root."""
    result = _run_guard({"tool_name": "Write", "tool_input": {"file_path": path}}, "/app")
    assert result.returncode == 2, result.stdout


@pytest.mark.parametrize(
    "path", ["/home/cbc/.claude/settings.json", "/tmp/pricebooks/scratch.pdf"]
)
def test_a_directory_of_the_same_name_elsewhere_is_not_this_project(path: str) -> None:
    """The rule is about this repository, not about a word.

    Matching a bare path segment blocked the user's own ~/.claude - their settings,
    their notes - which is not what the file-safety rule protects.
    """
    result = _run_guard({"tool_name": "Write", "tool_input": {"file_path": path}}, "/app")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "path",
    [
        "projects/dutch_bros/extracted/door_schedule.json",
        "projects/dutch_bros/priced/line_items.json",
        "/app/projects/x/review/review_flags.json",
        # Names the directory without being in it.
        "projects/pricebooks_notes/summary.md",
    ],
)
def test_writing_inside_a_project_is_allowed(path: str) -> None:
    result = _run_guard({"tool_name": "Write", "tool_input": {"file_path": path}})
    assert result.returncode == 0, result.stderr


def test_bash_deletion_guard_still_applies() -> None:
    protected = "reference-library/margins"
    result = _run_guard(
        {"tool_name": "Bash", "tool_input": {"command": f"rm -rf {protected}"}}
    )
    assert result.returncode == 2


def test_plain_rm_on_claude_hooks_is_blocked() -> None:
    result = _run_guard(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "rm .claude/hooks/pre_delete_guard.py"},
        }
    )
    assert result.returncode == 2, result.stderr


def test_mcp_argument_targeting_pricebooks_is_blocked() -> None:
    result = _run_guard(
        {
            "tool_name": "mcp__artifact-storage__save_artifact",
            "tool_input": {
                "project": "demo",
                "path": "pricebooks/hager.pdf",
                "content": "{}",
            },
        }
    )
    assert result.returncode == 2, result.stderr


def test_mcp_p21_write_tool_name_is_blocked() -> None:
    result = _run_guard(
        {
            "tool_name": "mcp__p21-connector__update_item",
            "tool_input": {"part_number": "3500"},
        }
    )
    assert result.returncode == 2, result.stderr
    assert "NFR-5" in result.stderr


# â”€â”€ the guard blocks writes, and only writes â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#
# The rule these enforce is about *writing* to reference data. A pricing pass
# exists to read price books, so a guard that blocks reads is not enforcing the
# rule - it is breaking it. Both halves are pinned because the guard has been
# wrong in both directions: a substring scan once blocked reads, unrelated home
# directories, and any file whose text merely mentioned a protected path, while
# the version before that let every write through that was not a deletion.


@pytest.mark.parametrize(
    "command",
    [
        "echo x > pricebooks/index.json",
        "echo x >> pricebooks/index.json",
        "cp evil.json pricebooks/index.json",
        "cp evil.py .claude/hooks/pre_delete_guard.py",
        "mv x.json reference-library/margins/x.json",
        "sed -i s/a/b/ pricebooks/index.json",
        "echo x | tee pricebooks/index.json",
        "rm pricebooks/hager_price_book_18.pdf",
    ],
)
def test_writing_into_reference_data_is_blocked(command: str) -> None:
    """Not only deletion. Every one of these but the last was allowed before."""
    result = _run_guard({"tool_name": "Bash", "tool_input": {"command": command}})
    assert result.returncode == 2, f"{command!r} should be blocked\n{result.stdout}"


@pytest.mark.parametrize(
    "command",
    [
        "cat pricebooks/index.json",
        "cp pricebooks/index.json /tmp/x.json",   # copies *out* of it
        "sed s/a/b/ pricebooks/index.json",       # no -i, so it only reads
        "grep -rn hager pricebooks/",
        "ls reference-library/margins",
        "git diff -- .claude/hooks/pre_delete_guard.py",
        "echo x > projects/demo/notes.md",
        "rm projects/demo/uploads/tmp.json",
    ],
)
def test_reading_reference_data_is_allowed(command: str) -> None:
    """The pipeline's actual job. Blocking these is the failure mode, not safety."""
    result = _run_guard({"tool_name": "Bash", "tool_input": {"command": command}})
    assert result.returncode == 0, f"{command!r} should be allowed\n{result.stderr}"


def test_prose_naming_a_protected_path_is_not_a_write() -> None:
    """A command whose *text* mentions the rule is not an attempt to break it.

    The substring branch matched the word anywhere in the command, so a heredoc
    writing documentation about the guard was refused by the guard.
    """
    heredoc = (
        "cat >> notes.md <<'EOF'\n"
        "every write through that was not an `rm`\n"
        'blocked: "cp evil.json pricebooks/index.json"\n'
        "EOF"
    )
    result = _run_guard({"tool_name": "Bash", "tool_input": {"command": heredoc}})
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "heredoc",
    [
        (
            "python - <<'PY'\n"
            "text = '`rm -rf` outside `projects/`, and `git push`'\n"
            "Path('docs/guardrails.md').write_text(text)\n"
            "PY"
        ),
        (
            "python - <<'PY'\n"
            "step = 'sudo chown -R 1000:1000 projects pricebooks'\n"
            "Path('.github/workflows/ci.yml').write_text(step)\n"
            "PY"
        ),
    ],
)
def test_heredoc_bodies_do_not_trigger_command_text_scans(heredoc: str) -> None:
    """Documentation inside a heredoc is not shell â€” only the prefix is scanned."""
    result = _run_guard({"tool_name": "Bash", "tool_input": {"command": heredoc}})
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "command,rule",
    [
        ("git push origin main", "git-push"),
        ("sudo chown -R 1000:1000 pricebooks", "protected-bash-write"),
    ],
)
def test_real_forbidden_commands_still_block_and_name_the_rule(
    command: str, rule: str
) -> None:
    result = _run_guard({"tool_name": "Bash", "tool_input": {"command": command}})
    assert result.returncode == 2, result.stdout
    assert f"rule={rule}" in result.stderr


def test_an_mcp_read_tool_may_name_a_price_book() -> None:
    """The counterpart to the save_artifact test above.

    Scanning every argument of every MCP tool blocked `extract_text` on a vendor
    sheet - the exact call a pricing pass exists to make.
    """
    result = _run_guard(
        {
            "tool_name": "mcp__pdf-tools__extract_text",
            "tool_input": {"path": "pricebooks/hager_price_book_18.pdf", "page": 12},
        }
    )
    assert result.returncode == 0, result.stderr


def test_an_mcp_write_tool_may_still_write_inside_a_project() -> None:
    result = _run_guard(
        {
            "tool_name": "mcp__artifact-storage__save_artifact",
            "tool_input": {
                "project": "demo",
                "path": "projects/demo/priced/line_items.json",
                "content": "{}",
            },
        }
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "path", ["/tmp/pricebooks/scratch.pdf", "/home/cbc/.claude/settings.json"]
)
def test_a_protected_name_outside_the_project_is_not_protected(path: str) -> None:
    """A directory of the same name elsewhere is not this repository's."""
    result = _run_guard(
        {"tool_name": "Bash", "tool_input": {"command": f"cp x.json {path}"}}, "/app"
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "command",
    [
        # The command word hidden behind shell punctuation or a wrapper word.
        "(cp evil.json pricebooks/index.json)",
        "(cp evil.json pricebooks/index.json 2>&1 || true)",
        "sudo cp evil.json pricebooks/index.json",
        "FOO=bar cp evil.json pricebooks/index.json",
        "true && cp evil.json pricebooks/index.json",
        "true; cp evil.json pricebooks/index.json",
        "echo x >pricebooks/index.json",
        "echo x | tee -a pricebooks/index.json",
        "sed -i.bak s/a/b/ pricebooks/index.json",
        "truncate -s 0 pricebooks/index.json",
        "cp evil.json ./pricebooks/index.json",
        "cp evil.json projects/../pricebooks/index.json",
    ],
)
def test_a_write_hidden_behind_shell_syntax_is_still_blocked(command: str) -> None:
    """The command word is not always the first word.

    `(cp CLAUDE.md pricebooks/index.json 2>&1 || true)` tokenises with the paren
    attached, so the name read as "(cp" and matched nothing - and `2>&1` then made
    itself the last argument, hiding the real destination behind it. That pair is
    not hypothetical: together they overwrote the price-book index during this
    work, which is why each spelling is pinned separately.
    """
    result = _run_guard({"tool_name": "Bash", "tool_input": {"command": command}})
    assert result.returncode == 2, f"{command!r} should be blocked\n{result.stdout}"


def test_a_quoted_absolute_path_into_reference_data_is_blocked() -> None:
    """Resolution, not spelling: the absolute form is the same directory."""
    target = (ROOT / "pricebooks" / "index.json").as_posix()
    result = _run_guard(
        {"tool_name": "Bash", "tool_input": {"command": f'cp evil.json "{target}"'}}
    )
    assert result.returncode == 2, result.stdout


@pytest.mark.xfail(strict=True, reason=(
    "pre_delete_guard.PROTECTED_DIRS names repo-root pricebooks/ and "
    "reference-library/. The data moved to data/pricebooks and "
    "data/reference-library in the monolith cutover and the hook was not told: "
    "writes and deletes there exit 0. The container is covered only because the "
    "Dockerfile symlinks /app/pricebooks. Strict, so fixing the hook fails this "
    "marker and it gets removed."
))
@pytest.mark.parametrize(
    "command",
    [
        "cp evil.json data/pricebooks/index.json",
        "rm data/pricebooks/hager_price_book_18.pdf",
        "cp evil.json data/reference-library/margins/margin_framework.json",
    ],
)
def test_a_write_into_the_real_reference_data_dirs_is_blocked(command: str) -> None:
    """Where the reference data actually lives in a checkout."""
    result = _run_guard({"tool_name": "Bash", "tool_input": {"command": command}})
    assert result.returncode == 2, f"{command!r} should be blocked"


@pytest.mark.parametrize(
    "command",
    [
        "(cat pricebooks/index.json || true)",
        "sudo cat pricebooks/index.json",
        "true && grep hager pricebooks/index.json",
    ],
)
def test_a_read_hidden_behind_shell_syntax_is_still_allowed(command: str) -> None:
    """Unwrapping the command must not turn reads into writes."""
    result = _run_guard({"tool_name": "Bash", "tool_input": {"command": command}})
    assert result.returncode == 0, f"{command!r} should be allowed\n{result.stderr}"


# â”€â”€ the worker must not lose or duplicate a job it is holding â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_a_failed_heartbeat_does_not_kill_the_heartbeat(monkeypatch) -> None:
    """One transient Mongo error used to end the beat for the whole run.

    The task died with its exception never retrieved; ninety seconds later
    reap_abandoned saw a stale heartbeat and requeued a job that was still
    running, and another worker claimed it - two Claude passes over one project
    directory, from one blip during a forty-minute pipeline.
    """
    import asyncio

    from cbc.modules.ops.api import worker

    calls: list[int] = []

    class _Jobs:
        async def update_one(self, *_args, **_kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("connection reset by peer")
            return None

    class _Db:
        jobs = _Jobs()

    monkeypatch.setattr(worker, "jobs_collection", lambda: _Db.jobs)
    monkeypatch.setattr(worker, "HEARTBEAT_SECONDS", 0)

    async def drive() -> None:
        task = asyncio.create_task(worker.beat("job-1", "worker-1", 3))
        while len(calls) < 3:
            await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(asyncio.wait_for(drive(), timeout=5))
    assert len(calls) >= 3, "the beat stopped at the first failure"


def test_the_shutdown_requeue_is_guarded_like_finish() -> None:
    """A requeue that ignores ownership hands a live job to a second worker.

    finish() writes under {_id, workerId, claimGeneration}. The shutdown path
    wrote under {_id} alone, so a worker whose job had already been reaped and
    re-claimed requeued it out from under the run that held it. It also fired
    regardless of whether the pass had succeeded, throwing away a completed
    three-hour extraction when SIGTERM landed just before finish().

    Anchored on the note the requeue writes rather than on line numbers.
    """
    import inspect

    from cbc.modules.ops.api import claude_pass, worker as ops_worker

    # The pass decides that a shutdown interrupted a failed run; ops does the
    # requeue, under the claim. Read both, so neither guard can quietly go.
    source = inspect.getsource(claude_pass.run)
    call = source.index("requeue_for_shutdown(job)")
    block = source[source.rindex("if ops_worker.stopping()", 0, call) : call]
    assert "not result.ok" in block, "a successful run is still discarded on shutdown"

    requeue = inspect.getsource(ops_worker.requeue_for_shutdown)
    assert '"worker shut down mid-run; requeued"' in requeue, "the shutdown requeue is gone"
    assert "owns_job(job, current)" in requeue, "the requeue does not check ownership"
    assert '"claimGeneration": job.get("claimGeneration")' in requeue, (
        "the requeue write is not filtered by this worker's claim"
    )


def test_sync_results_checks_the_fencing_token() -> None:
    import importlib
    import inspect

    from cbc.modules.extraction.api import passes

    source = inspect.getsource(passes.check_output)
    assert "holds_lease" in source
    assert "lease stolen" in source
    # And every pass slice asks it before its sync writes anything.
    for slice_ in ("extraction.features.ExtractBidSet", "quoting.features.MatchAndPrice",
                   "quoting.features.BuildProposal", "intake.features.IngestAddendum",
                   "intake.features.RunFullPipeline"):
        sync = inspect.getsource(importlib.import_module(f"cbc.modules.{slice_}").sync_results)
        assert sync.index("await passes.check_output(job, project)") == sync.index("await "), slice_


def test_heartbeat_watchdog_fires_while_blocked() -> None:
    import time

    from cbc.core.claude_cli import HeartbeatWatchdog

    hits: list[int] = []

    def ping() -> None:
        hits.append(1)

    dog = HeartbeatWatchdog(ping, 0.12)
    dog.start()
    time.sleep(0.4)
    dog.stop()
    assert len(hits) >= 2

