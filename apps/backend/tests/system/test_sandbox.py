"""Per-job scratch allowlist: only known Claude outputs are promoted."""
from __future__ import annotations

import json

import pytest

from cbc.worker_kit import sandbox


def test_allowlist_accepts_known_outputs() -> None:
    assert sandbox.allowed_relpath("extracted/line_items.json")
    assert sandbox.allowed_relpath("priced/line_items.json")
    assert sandbox.allowed_relpath("review/review_flags.json")
    assert sandbox.allowed_relpath("quotation.html")


def test_allowlist_rejects_escapes_and_secrets() -> None:
    assert not sandbox.allowed_relpath("../other-slug/extracted/x.json")
    assert not sandbox.allowed_relpath("extracted/../../.ssh/id_rsa")
    assert not sandbox.allowed_relpath(".ssh/id_rsa")
    assert not sandbox.allowed_relpath("uploads/raw/evil.pdf")


def test_promote_copies_allowlisted_files_only(tmp_path, monkeypatch) -> None:
    from cbc.shared.config import settings

    previous = settings.storage_root
    settings.storage_root = tmp_path
    try:
        job_id = "job1"
        slug = "demo"
        live = tmp_path / slug
        live.mkdir()
        workspace = sandbox.prepare(slug)
        clone = workspace / "projects" / slug
        (clone / "extracted").mkdir(parents=True, exist_ok=True)
        (clone / "extracted" / "line_items.json").write_text("{}", encoding="utf-8")
        (clone / ".ssh").mkdir(exist_ok=True)
        (clone / ".ssh" / "id_rsa").write_text("secret", encoding="utf-8")
        (clone / "stolen.txt").write_text("nope", encoding="utf-8")
        promoted = sandbox.promote(slug)
        assert "extracted/line_items.json" in promoted
        assert (live / "extracted" / "line_items.json").is_file()
        assert not (live / ".ssh" / "id_rsa").exists()
        assert not (live / "stolen.txt").exists()
    finally:
        sandbox.cleanup(slug)
        settings.storage_root = previous


def test_docker_sandbox_is_skipped_without_a_socket(monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_SANDBOX", "docker")
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setattr(sandbox.shutil, "which", lambda _name: None)
    assert sandbox.mode() == "docker"
    assert sandbox.docker_available() is False
    result = sandbox.run_claude_docker("hi", cwd=None)
    assert result.ok is False
    assert result.error_code == "sandbox_unavailable"


def test_ensure_workspace_trusted_writes_claude_json(tmp_path) -> None:
    workspace = tmp_path / "scratch" / "workspace"
    workspace.mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    assert sandbox.ensure_workspace_trusted(workspace, home=home) is True
    config = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
    key = str(workspace.resolve())
    assert config["projects"][key]["hasTrustDialogAccepted"] is True
    # Idempotent — second call does not rewrite as a change.
    assert sandbox.ensure_workspace_trusted(workspace, home=home) is False


def test_prepare_marks_scratch_workspace_trusted(tmp_path, monkeypatch) -> None:
    from cbc.shared.config import settings

    previous = settings.storage_root
    settings.storage_root = tmp_path
    trusted: list = []

    def _record(workspace, home=None):  # noqa: ARG001
        trusted.append(workspace)
        return True

    monkeypatch.setattr(sandbox, "ensure_workspace_trusted", _record)
    try:
        workspace = sandbox.prepare("demo")
        assert trusted == [workspace]
    finally:
        sandbox.cleanup("demo")
        settings.storage_root = previous


def test_promote_rejects_empty_priced_over_live_quote(tmp_path) -> None:
    """Empty scratch line_items must not erase a live priced quote."""
    from cbc.shared.config import settings
    from cbc.worker_kit.sandbox import EmptyPricingPromoteError

    previous = settings.storage_root
    settings.storage_root = tmp_path
    try:
        slug = "demo"
        live = tmp_path / slug
        (live / "priced").mkdir(parents=True)
        (live / "priced" / "line_items.json").write_text(
            json.dumps({"lines": [{"part_number": "X", "cost": 1.0}]}),
            encoding="utf-8",
        )
        workspace = sandbox.prepare(slug)
        clone = workspace / "projects" / slug
        (clone / "priced").mkdir(parents=True, exist_ok=True)
        (clone / "priced" / "line_items.json").write_text(
            json.dumps({"lines": [], "generated_by": "estimator-approved via Ops-Hub"}),
            encoding="utf-8",
        )
        with pytest.raises(EmptyPricingPromoteError):
            sandbox.promote(slug)
        live_payload = json.loads((live / "priced" / "line_items.json").read_text())
        assert len(live_payload["lines"]) == 1
    finally:
        sandbox.cleanup(slug)
        settings.storage_root = previous


def test_promote_replaces_unwritable_live_targets(tmp_path, monkeypatch) -> None:
    """Host/root-owned live files must not abort the rest of promote."""
    from pathlib import Path

    from cbc.shared.config import settings

    previous = settings.storage_root
    settings.storage_root = tmp_path
    try:
        slug = "demo"
        live = tmp_path / slug
        (live / "extracted").mkdir(parents=True)
        blocked = live / "extracted" / "div10_takeoff.json"
        blocked.write_text('{"stale": true}', encoding="utf-8")
        workspace = sandbox.prepare(slug)
        clone = workspace / "projects" / slug
        (clone / "extracted").mkdir(parents=True, exist_ok=True)
        (clone / "extracted" / "div10_takeoff.json").write_text(
            '{"fresh": true}', encoding="utf-8"
        )
        (clone / "extracted" / "hardware_sets.json").write_text("[]", encoding="utf-8")
        (clone / "priced").mkdir(parents=True, exist_ok=True)
        (clone / "priced" / "line_items.json").write_text(
            json.dumps({"lines": [{"part_number": "Y", "cost": 2.0}]}),
            encoding="utf-8",
        )

        real_copy2 = sandbox.shutil.copy2
        calls = {"n": 0}

        def flaky_copy2(src, dst, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1 and Path(dst).name == "div10_takeoff.json":
                raise PermissionError("simulated root-owned target")
            return real_copy2(src, dst, *args, **kwargs)

        monkeypatch.setattr(sandbox.shutil, "copy2", flaky_copy2)
        promoted = sandbox.promote(slug)
        assert "extracted/div10_takeoff.json" in promoted
        assert "extracted/hardware_sets.json" in promoted
        assert "priced/line_items.json" in promoted
        assert '"fresh"' in blocked.read_text(encoding="utf-8")
        assert (live / "priced" / "line_items.json").is_file()
    finally:
        sandbox.cleanup(slug)
        settings.storage_root = previous


def test_promote_appends_the_audit_trail_and_keeps_artifact_versions(tmp_path) -> None:
    """A run's audit trail (NFR-3) and artifact-storage's versions used to be discarded."""
    from cbc.shared.config import settings

    previous = settings.storage_root
    settings.storage_root = tmp_path
    try:
        slug = "demo"
        live = tmp_path / slug
        live.mkdir()
        (live / "audit_trail.jsonl").write_text('{"tool_name": "before"}\n', encoding="utf-8")
        workspace = sandbox.prepare(slug)
        clone = workspace / "projects" / slug
        with (clone / "audit_trail.jsonl").open("a", encoding="utf-8") as handle:
            handle.write('{"tool_name": "Read"}\n{"tool_name": "mcp__artifact-storage__save_artifact"}\n')
        digest = "a" * 64
        (clone / ".versions").mkdir()
        (clone / ".versions" / digest).write_text("{}", encoding="utf-8")
        (clone / ".versions" / "versions.jsonl").write_text(json.dumps({"sha256": digest}) + "\n", encoding="utf-8")
        (clone / ".versions" / "not-a-digest").write_text("nope", encoding="utf-8")

        promoted = sandbox.promote(slug)

        trail = (live / "audit_trail.jsonl").read_text(encoding="utf-8").splitlines()
        assert [json.loads(line)["tool_name"] for line in trail] == [
            "before", "Read", "mcp__artifact-storage__save_artifact",
        ]
        assert "audit_trail.jsonl" in promoted
        assert (live / ".versions" / digest).is_file()
        assert (live / ".versions" / "versions.jsonl").is_file()
        assert not (live / ".versions" / "not-a-digest").exists()

        sandbox.promote(slug)
        assert len((live / "audit_trail.jsonl").read_text(encoding="utf-8").splitlines()) == 3, (
            "promoting the same clone twice appends nothing twice"
        )
    finally:
        sandbox.cleanup(slug)
        settings.storage_root = previous


def test_the_workspace_path_is_stable_across_jobs_on_one_bid(tmp_path, monkeypatch):
    """Claude Code's prompt cache is a prefix match, and cwd is in the prefix.

    A four-run probe against this CLI: two runs from one directory, then the
    same prompt with byte-identical files from a second directory. The second
    directory cost $0.0404 against $0.0056 - 7.2x - and wrote exactly as many
    cache tokens as the first cold run. Keying scratch by job id meant every
    job, every retry and every wave leg paid that.

    The clone is still wiped and rebuilt per job; only the name is stable.
    """
    from cbc.shared.config import settings
    from cbc.worker_kit import sandbox

    previous = settings.storage_root
    settings.storage_root = tmp_path
    try:
        first = sandbox.workspace_dir("dutch_bros")
        second = sandbox.workspace_dir("dutch_bros")
        assert first == second, "two jobs on one bid must agree on the path"
        assert sandbox.workspace_dir("wendys_acheson") != first, "bids stay apart"
        assert "dutch_bros" in str(first)
    finally:
        settings.storage_root = previous


def test_a_failed_promote_survives_the_next_job_on_the_same_bid(tmp_path, monkeypatch):
    """Per-job scratch kept a failed clone alive for free; per-project does not.

    `cleanup` drops the workspace only, and a promote failure moves the clone
    beside it, so the next job's rebuild cannot take the one copy of work that
    never reached the live bid.
    """
    from cbc.shared.config import settings
    from cbc.worker_kit import sandbox

    previous = settings.storage_root
    settings.storage_root = tmp_path
    try:
        kept = sandbox.quarantine_dir("dutch_bros", "6aa7fad37aef9b8dec0a1d45")
        kept.mkdir(parents=True)
        (kept / "line_items.json").write_text("[]", encoding="utf-8")

        workspace = sandbox.workspace_dir("dutch_bros")
        workspace.mkdir(parents=True, exist_ok=True)
        sandbox.cleanup("dutch_bros")

        assert not workspace.exists(), "the clone goes"
        assert (kept / "line_items.json").is_file(), "the quarantined copy stays"
    finally:
        settings.storage_root = previous
