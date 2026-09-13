"""Per-job scratch allowlist: only known Claude outputs are promoted."""
from __future__ import annotations

import json

from cbc.worker_kit import sandbox


def test_allowlist_accepts_known_outputs() -> None:
    assert sandbox.allowed_relpath("extracted/door_schedule.json")
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
        workspace = sandbox.prepare(job_id, slug)
        clone = workspace / "projects" / slug
        (clone / "extracted").mkdir(parents=True, exist_ok=True)
        (clone / "extracted" / "door_schedule.json").write_text("{}", encoding="utf-8")
        (clone / ".ssh").mkdir(exist_ok=True)
        (clone / ".ssh" / "id_rsa").write_text("secret", encoding="utf-8")
        (clone / "stolen.txt").write_text("nope", encoding="utf-8")
        promoted = sandbox.promote(job_id, slug)
        assert "extracted/door_schedule.json" in promoted
        assert (live / "extracted" / "door_schedule.json").is_file()
        assert not (live / ".ssh" / "id_rsa").exists()
        assert not (live / "stolen.txt").exists()
    finally:
        sandbox.cleanup("job1")
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
        workspace = sandbox.prepare("job-trust", "demo")
        assert trusted == [workspace]
    finally:
        sandbox.cleanup("job-trust")
        settings.storage_root = previous
